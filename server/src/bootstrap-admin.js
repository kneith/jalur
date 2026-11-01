import 'dotenv/config';
import { pool } from './store.js';
import { hashPassword } from './security.js';
const {SCHOOL_NAME,SCHOOL_CODE,ADMIN_NAME,ADMIN_EMAIL,ADMIN_PASSWORD}=process.env;
if(!SCHOOL_NAME||!SCHOOL_CODE||!ADMIN_NAME||!ADMIN_EMAIL||!ADMIN_PASSWORD){console.error('Set SCHOOL_NAME, SCHOOL_CODE, ADMIN_NAME, ADMIN_EMAIL, ADMIN_PASSWORD in server/.env before running bootstrap.');process.exit(1);}
if(ADMIN_PASSWORD.length<14){console.error('ADMIN_PASSWORD must be at least 14 characters.');process.exit(1);}
try{
 const client=await pool.connect();try{await client.query('BEGIN');
  const school=await client.query('INSERT INTO schools(name,code) VALUES($1,$2) ON CONFLICT(code) DO UPDATE SET name=EXCLUDED.name RETURNING id',[SCHOOL_NAME,SCHOOL_CODE]);
  const passwordHash=await hashPassword(ADMIN_PASSWORD);
  await client.query(`INSERT INTO users(school_id,email,full_name,password_hash,role) VALUES($1,lower($2),$3,$4,'school_admin') ON CONFLICT(school_id,email) DO UPDATE SET full_name=EXCLUDED.full_name,password_hash=EXCLUDED.password_hash,status='active'`,[school.rows[0].id,ADMIN_EMAIL,ADMIN_NAME,passwordHash]);
  await client.query('COMMIT');console.log('School and school administrator provisioned. Remove ADMIN_PASSWORD from shell history and rotate it after first login.');
 }catch(e){await client.query('ROLLBACK');throw e;}finally{client.release();}
}finally{await pool.end();}
