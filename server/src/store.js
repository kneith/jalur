import pg from 'pg';
const { Pool } = pg;
export const pool = new Pool({connectionString:process.env.DATABASE_URL, max:15, idleTimeoutMillis:30000, connectionTimeoutMillis:5000, ssl:process.env.PGSSL==='true'?{rejectUnauthorized:true}:undefined});
export async function audit(req,action,entityType,entityId=null){
  // Audit events intentionally omit sensitive payloads and are never written for anonymous venting.
  await pool.query('INSERT INTO audit_events(school_id,actor_id,action,entity_type,entity_id) VALUES($1,$2,$3,$4,$5)',[req.user?.school_id||null,req.user?.id||null,action,entityType,String(entityId||'')||null]);
}
