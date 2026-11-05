
import 'dotenv/config';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { pool } from './store.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const source = process.argv[2] || path.resolve(here, '../../data/database.js');
const BATCH_SIZE = 250;

const EXPECTED_INSTITUTIONS = 4303;
const EXPECTED_PROGRAMS = 34709;

const raw = await fs.readFile(source, 'utf8');

const json = raw
  .replace(/^\s*\/\*[\s\S]*?\*\/\s*/, '')
  .trim()
  .replace(/^window\.JALUR_DB_RAW\s*=\s*/, '')
  .replace(/;\s*$/, '');

const db = JSON.parse(json);

const mapRows = (headers, rows) =>
  rows.map(row =>
    Object.fromEntries(headers.map((h, i) => [h, row[i] ?? null]))
  );

if (!Array.isArray(db.ik) || !Array.isArray(db.i) ||
    !Array.isArray(db.pk) || !Array.isArray(db.p)) {
  throw new Error('Struktur database.js tidak sesuai.');
}

const institutions = mapRows(db.ik, db.i);
const programs = mapRows(db.pk, db.p);

if (
  institutions.length !== EXPECTED_INSTITUTIONS ||
  programs.length !== EXPECTED_PROGRAMS
) {
  throw new Error(
    `Jumlah data sumber tidak sesuai. Institusi: ${institutions.length}, Program: ${programs.length}.`
  );
}

function makeInstitution(d) {
  const id = String(d.id ?? d.code ?? `${d.name}-${d.city || ''}`);
  const name = String(d.name || 'Nama tidak tersedia');
  const search = [
    name, d.city, d.province, d.form, d.management, d.code
  ].filter(Boolean).join(' ');

  return [id, name, search, JSON.stringify(d)];
}

function makeProgram(d) {
  const id = String(d.id ?? `${d.institutionId}-${d.code}-${d.name}`);
  const name = String(d.name || 'Nama tidak tersedia');
  const institutionName = String(d.institution || d.institutionName || '');
  const search = [
    name, institutionName, d.campus, d.level,
    d.field, d.group, d.code, d.status
  ].filter(Boolean).join(' ');

  return [
    id,
    d.institutionId == null ? null : String(d.institutionId),
    name,
    institutionName,
    d.level == null ? null : String(d.level),
    d.field == null ? null : String(d.field),
    search,
    JSON.stringify(d)
  ];
}

async function insertBatch(client, table, columns, rows, jsonIndexes, updates) {
  if (!rows.length) return;

  // Pertahankan perilaku upsert berurutan jika ada ID duplikat.
  const uniqueRows = [...new Map(rows.map(row => [row[0], row])).values()];

  const values = [];

  const tuples = uniqueRows.map(row => {
    const placeholders = row.map((value, index) => {
      values.push(value);
      const placeholder = `$${values.length}`;
      return jsonIndexes.includes(index) ? `${placeholder}::jsonb` : placeholder;
    });

    return `(${placeholders.join(',')})`;
  });

  const sql = `
    INSERT INTO ${table} (${columns.join(',')})
    VALUES ${tuples.join(',')}
    ON CONFLICT(id) DO UPDATE SET
      ${updates.join(',')},
      imported_at = now()
  `;

  await client.query(sql, values);

  return uniqueRows.length;
}

const client = await pool.connect();

let transactionStarted = false;
let totalI = 0;
let totalP = 0;

try {
  console.log('Memulai impor direktori JALUR...');
  console.log(`Sumber: ${source}`);
  console.log(`Institusi: ${institutions.length}`);
  console.log(`Program: ${programs.length}`);

  await client.query('BEGIN');
  transactionStarted = true;

  for (let i = 0; i < institutions.length; i += BATCH_SIZE) {
    const batch = institutions
      .slice(i, i + BATCH_SIZE)
      .map(makeInstitution);

    const inserted = await insertBatch(
      client,
      'directory_institutions',
      ['id', 'name', 'search_text', 'data'],
      batch,
      [3],
      [
        'name=EXCLUDED.name',
        'search_text=EXCLUDED.search_text',
        'data=EXCLUDED.data'
      ]
    );

    totalI += batch.length;

    console.log(
      `[Institusi] ${totalI}/${institutions.length} | batch ${inserted} baris`
    );
  }

  for (let i = 0; i < programs.length; i += BATCH_SIZE) {
    const batch = programs
      .slice(i, i + BATCH_SIZE)
      .map(makeProgram);

    const inserted = await insertBatch(
      client,
      'directory_programs',
      [
        'id', 'institution_id', 'name', 'institution_name',
        'level', 'field', 'search_text', 'data'
      ],
      batch,
      [7],
      [
        'institution_id=EXCLUDED.institution_id',
        'name=EXCLUDED.name',
        'institution_name=EXCLUDED.institution_name',
        'level=EXCLUDED.level',
        'field=EXCLUDED.field',
        'search_text=EXCLUDED.search_text',
        'data=EXCLUDED.data'
      ]
    );

    totalP += batch.length;

    console.log(
      `[Program] ${totalP}/${programs.length} | batch ${inserted} baris`
    );
  }

  await client.query('COMMIT');
  transactionStarted = false;

  console.log('\nIMPORTED SUCCESSFULLY');
  console.log(JSON.stringify({
    institutions: totalI,
    programs: totalP,
    source
  }, null, 2));

} catch (error) {
  if (transactionStarted) {
    try {
      await client.query('ROLLBACK');
      console.error('Transaksi dibatalkan (ROLLBACK).');
    } catch (rollbackError) {
      console.error('ROLLBACK gagal:', rollbackError.message);
    }
  }

  console.error('IMPORT FAILED:', error);
  process.exitCode = 1;

} finally {
  client.release();
  await pool.end();
}
