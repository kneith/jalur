import pg from 'pg';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const caPath = path.resolve(here, '../supabase-ca.crt');

const ssl = process.env.PGSSL === 'true'
  ? {
      ca: fs.readFileSync(caPath, 'utf8'),
      rejectUnauthorized: true
    }
  : undefined;

export const pool = new pg.Pool({
  connectionString: process.env.DATABASE_URL,
  max: 15,
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 5000,
  ssl
});

export async function audit(req, action, entityType, entityId = null) {
  await pool.query(
    'INSERT INTO audit_events(school_id,actor_id,action,entity_type,entity_id) VALUES($1,$2,$3,$4,$5)',
    [
      req.user?.school_id || null,
      req.user?.id || null,
      action,
      entityType,
      String(entityId || '') || null
    ]
  );
}