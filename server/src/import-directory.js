import 'dotenv/config';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { pool } from './store.js';
const here=path.dirname(fileURLToPath(import.meta.url));
const source=process.argv[2]||path.resolve(here,'../../data/database.js');
const raw=await fs.readFile(source,'utf8');
const json=raw.replace(/^\s*\/\*[\s\S]*?\*\/\s*/, '').trim().replace(/^window\.JALUR_DB_RAW\s*=\s*/, '').replace(/;\s*$/, '');
const db=JSON.parse(json);
const mapRows=(headers,rows)=>rows.map(row=>Object.fromEntries(headers.map((h,i)=>[h,row[i]??null])));
const institutions=mapRows(db.ik,db.i);const programs=mapRows(db.pk,db.p);
const client=await pool.connect();let totalI=0,totalP=0;
try{
 await client.query('BEGIN');
 for(let i=0;i<institutions.length;i+=250){
  for(const d of institutions.slice(i,i+250)){
   const id=String(d.id??d.code??`${d.name}-${d.city||''}`);const name=String(d.name||'Nama tidak tersedia');const search=[name,d.city,d.province,d.form,d.management,d.code].filter(Boolean).join(' ');
   await client.query('INSERT INTO directory_institutions(id,name,search_text,data) VALUES($1,$2,$3,$4::jsonb) ON CONFLICT(id) DO UPDATE SET name=EXCLUDED.name,search_text=EXCLUDED.search_text,data=EXCLUDED.data,imported_at=now()',[id,name,search,JSON.stringify(d)]);totalI++;
  }
 }
 for(let i=0;i<programs.length;i+=250){
  for(const d of programs.slice(i,i+250)){
   const id=String(d.id??`${d.institutionId}-${d.code}-${d.name}`);const name=String(d.name||'Nama tidak tersedia');const institutionName=String(d.institution||d.institutionName||'');const search=[name,institutionName,d.campus,d.level,d.field,d.group,d.code,d.status].filter(Boolean).join(' ');
   await client.query('INSERT INTO directory_programs(id,institution_id,name,institution_name,level,field,search_text,data) VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb) ON CONFLICT(id) DO UPDATE SET institution_id=EXCLUDED.institution_id,name=EXCLUDED.name,institution_name=EXCLUDED.institution_name,level=EXCLUDED.level,field=EXCLUDED.field,search_text=EXCLUDED.search_text,data=EXCLUDED.data,imported_at=now()',[id,d.institutionId==null?null:String(d.institutionId),name,institutionName,d.level==null?null:String(d.level),d.field==null?null:String(d.field),search,JSON.stringify(d)]);totalP++;
  }
 }
 await client.query('COMMIT');console.log(JSON.stringify({institutions:totalI,programs:totalP,source}));
}catch(e){await client.query('ROLLBACK');throw e;}finally{client.release();await pool.end();}
