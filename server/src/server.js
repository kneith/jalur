import 'dotenv/config';
import express from 'express';
import helmet from 'helmet';
import cookieParser from 'cookie-parser';
import crypto from 'node:crypto';
import { rateLimit } from 'express-rate-limit';
import { pool } from './store.js';
import { digest } from './security.js';
import { router } from './routes.js';

for (const key of ['DATABASE_URL','SESSION_PEPPER','VENTING_ENCRYPTION_KEY']) if(!process.env[key]) { console.error(`Missing required environment variable: ${key}`); process.exit(1); }
if(process.env.SESSION_PEPPER.length<32){console.error('SESSION_PEPPER must be at least 32 characters.');process.exit(1);}
const app=express();
app.disable('x-powered-by');
app.set('trust proxy',process.env.TRUST_PROXY==='true'?1:false);
app.use(helmet({crossOriginResourcePolicy:{policy:'same-site'},contentSecurityPolicy:{directives:{defaultSrc:["'self'"],baseUri:["'self'"],frameAncestors:["'none'"],objectSrc:["'none'"],upgradeInsecureRequests:process.env.NODE_ENV==='production'?[]:null}}}));
app.use((req,res,next)=>{res.setHeader('Cache-Control','no-store');res.setHeader('X-Request-ID',crypto.randomUUID());next();});
app.use(express.json({limit:'32kb',strict:true}));
app.use(cookieParser());
app.use((req,res,next)=>{
  const origin=req.get('origin'); const allowed=process.env.FRONTEND_ORIGIN;
  if(origin && allowed && origin!==allowed) return res.status(403).json({error:'origin_not_allowed'});
  if(origin && allowed){res.setHeader('Access-Control-Allow-Origin',allowed);res.setHeader('Access-Control-Allow-Credentials','true');res.setHeader('Vary','Origin');res.setHeader('Access-Control-Allow-Headers','Content-Type, X-CSRF-Token');res.setHeader('Access-Control-Allow-Methods','GET, POST, PATCH, DELETE, OPTIONS');}
  if(req.method==='OPTIONS')return res.status(204).end();next();
});
app.use('/api/auth/login',rateLimit({windowMs:15*60*1000,limit:10,standardHeaders:true,legacyHeaders:false,message:{error:'rate_limited'}}));
app.use('/api/anonymous-ventings',rateLimit({windowMs:60*60*1000,limit:5,standardHeaders:true,legacyHeaders:false,message:{error:'rate_limited'}}));
app.use(async(req,res,next)=>{
  if(!req.path.startsWith('/api') || req.path==='/api/health' || req.path==='/api/auth/login' || req.path==='/api/anonymous-ventings' && req.method==='POST') return next();
  const token=req.cookies.jalur_session;if(!token)return next();
  try{
    const {rows}=await pool.query(`SELECT s.id AS session_id,s.csrf_hash,s.expires_at,u.id,u.school_id,u.email,u.full_name,u.role,u.status,sc.status AS school_status FROM sessions s JOIN users u ON u.id=s.user_id LEFT JOIN schools sc ON sc.id=u.school_id WHERE s.token_hash=$1 AND s.expires_at>now()`,[digest(token)]);
    const u=rows[0];if(!u||u.status!=='active'||(u.school_id&&u.school_status!=='active'))return next();
    req.session={id:u.session_id,csrf_hash:u.csrf_hash};req.user={id:u.id,school_id:u.school_id,email:u.email,full_name:u.full_name,role:u.role};
    if(!['GET','HEAD','OPTIONS'].includes(req.method)){
      const csrf=req.get('x-csrf-token');if(!csrf||digest(csrf)!==u.csrf_hash)return res.status(403).json({error:'csrf_failed'});
    }
    pool.query('UPDATE sessions SET last_seen_at=now() WHERE id=$1',[u.session_id]).catch(()=>{});
    next();
  }catch(e){next(e);}
});
app.use('/api',router);
app.use((err,req,res,_next)=>{
  // Never log request bodies, cookies, passwords, grades, counseling notes, or venting text.
  console.error(JSON.stringify({level:'error',requestId:res.getHeader('X-Request-ID'),path:req.path,method:req.method,code:err.code||'internal_error'}));
  res.status(500).json({error:'internal_error',message:'Terjadi kesalahan. Gunakan ID permintaan saat menghubungi administrator.',requestId:res.getHeader('X-Request-ID')});
});
const port=Number(process.env.PORT||8080);
const server=app.listen(port,'0.0.0.0',()=>console.log(`JALUR API listening on ${port}`));
async function shutdown(){server.close(async()=>{await pool.end();process.exit(0);});}
process.on('SIGTERM',shutdown);process.on('SIGINT',shutdown);
