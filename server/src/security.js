import crypto from 'node:crypto';
import bcrypt from 'bcryptjs';

export const ROLES = Object.freeze({ STUDENT:'student', SCHOOL_ADMIN:'school_admin', TEACHER:'teacher', COUNSELOR:'counselor', WELLBEING_MODERATOR:'wellbeing_moderator', PLATFORM_ADMIN:'platform_admin' });
export const randomToken = (bytes=32) => crypto.randomBytes(bytes).toString('base64url');
export const digest = (value) => crypto.createHash('sha256').update(`${process.env.SESSION_PEPPER}:${value}`).digest('hex');
export const hashPassword = (password) => bcrypt.hash(password, 12);
export const verifyPassword = (password, hash) => bcrypt.compare(password, hash);

const encryptionKey = () => {
  const raw = process.env.VENTING_ENCRYPTION_KEY || '';
  let key;
  try { key = Buffer.from(raw, 'base64'); } catch { key = Buffer.alloc(0); }
  if (key.length !== 32) throw new Error('VENTING_ENCRYPTION_KEY harus berupa base64 dari tepat 32 byte.');
  return key;
};
export function encryptVenting(value) {
  const nonce = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', encryptionKey(), nonce);
  const encrypted = Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]);
  return { encrypted_payload: encrypted.toString('base64'), nonce: nonce.toString('base64'), auth_tag: cipher.getAuthTag().toString('base64') };
}
export function decryptVenting(row) {
  const decipher = crypto.createDecipheriv('aes-256-gcm', encryptionKey(), Buffer.from(row.nonce, 'base64'));
  decipher.setAuthTag(Buffer.from(row.auth_tag, 'base64'));
  return Buffer.concat([decipher.update(Buffer.from(row.encrypted_payload, 'base64')), decipher.final()]).toString('utf8');
}
