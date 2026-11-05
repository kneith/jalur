
import express from 'express';
import { z } from 'zod';
import { pool, audit } from './store.js';
import {
  digest,
  randomToken,
  hashPassword,
  verifyPassword,
  encryptVenting,
  decryptVenting,
  ROLES
} from './security.js';

export const router = express.Router();

const asyncRoute = fn => (req, res, next) =>
  Promise.resolve(fn(req, res, next)).catch(next);

const cleanText = (max = 300) =>
  z.string().trim().min(1).max(max);

const requireRole = (...roles) => (req, res, next) =>
  roles.includes(req.user?.role)
    ? next()
    : res.status(403).json({
        error: 'forbidden',
        message: 'Akses tidak diizinkan untuk peran ini.'
      });

const sameSchool = (req, res, next) => {
  if (req.user?.role === ROLES.PLATFORM_ADMIN || req.user?.school_id) {
    return next();
  }
  return res.status(403).json({ error: 'school_scope_required' });
};

// HEALTH
router.get('/health', asyncRoute(async (_req, res) => {
  await pool.query('SELECT 1');
  res.json({ ok: true, service: 'jalur-api' });
}));

// DIRECTORY
router.get('/directory/search', asyncRoute(async (req, res) => {
  const q = String(req.query.q || '').trim().slice(0, 120);
  const type = ['all', 'institution', 'program'].includes(req.query.type)
    ? req.query.type : 'all';

  const limit = Math.min(Math.max(Number.parseInt(req.query.limit || '25', 10) || 25, 1), 100);
  const offset = Math.max(Number.parseInt(req.query.offset || '0', 10) || 0, 0);

  if (!q) return res.json({ items: [], total: 0, limit, offset });

  const like = `%${q.replace(/[\\%_]/g, '\\$&')}%`;
  let items = [];
  let total = 0;

  if (type === 'institution' || type === 'all') {
    const r = await pool.query(
      `SELECT id, name, data FROM directory_institutions
       WHERE search_text ILIKE $1
       ORDER BY lower(name), id LIMIT $2 OFFSET $3`,
      [like, limit, offset]
    );

    items.push(...r.rows.map(x => ({
      type: 'institution',
      id: x.id,
      name: x.name,
      data: x.data
    })));

    const c = await pool.query(
      'SELECT count(*)::int AS n FROM directory_institutions WHERE search_text ILIKE $1',
      [like]
    );
    total += c.rows[0].n;
  }

  if (type === 'program' || type === 'all') {
    const r = await pool.query(
      `SELECT id, name, institution_name, level, field, data
       FROM directory_programs
       WHERE search_text ILIKE $1
       ORDER BY lower(name), lower(institution_name), id
       LIMIT $2 OFFSET $3`,
      [like, limit, offset]
    );

    items.push(...r.rows.map(x => ({
      type: 'program',
      id: x.id,
      name: x.name,
      institution_name: x.institution_name,
      level: x.level,
      field: x.field,
      data: x.data
    })));

    const c = await pool.query(
      'SELECT count(*)::int AS n FROM directory_programs WHERE search_text ILIKE $1',
      [like]
    );
    total += c.rows[0].n;
  }

  items.sort((a, b) =>
    a.name.localeCompare(b.name, 'id-ID') ||
    String(a.institution_name || '').localeCompare(
      String(b.institution_name || ''), 'id-ID'
    )
  );

  res.json({ items, total, limit, offset, alphabetical: true });
}));

// AUTH LOGIN
router.post('/auth/login', asyncRoute(async (req, res) => {
  const parsed = z.object({
    email: z.string().email().max(254),
    password: z.string().min(1).max(200)
  }).safeParse(req.body);

  if (!parsed.success) {
    return res.status(400).json({ error: 'invalid_input' });
  }

  const email = parsed.data.email.trim().toLowerCase();

  const { rows } = await pool.query(
    `SELECT u.id, u.school_id, u.email, u.full_name,
            u.password_hash, u.role, u.status,
            s.status AS school_status
     FROM users u
     LEFT JOIN schools s ON s.id = u.school_id
     WHERE lower(u.email) = lower($1)
     LIMIT 1`,
    [email]
  );

  const user = rows[0];

  if (
    !user ||
    !(await verifyPassword(parsed.data.password, user.password_hash)) ||
    user.status !== 'active' ||
    (user.school_id && user.school_status !== 'active')
  ) {
    return res.status(401).json({
      error: 'invalid_credentials',
      message: 'Email atau kata sandi tidak sesuai.'
    });
  }

  const session = randomToken(32);
  const csrf = randomToken(24);
  const ttl = Number(process.env.SESSION_TTL_HOURS || 12);

  await pool.query(
    `INSERT INTO sessions(user_id, token_hash, csrf_hash, expires_at)
     VALUES($1, $2, $3, now() + ($4 * interval '1 hour'))`,
    [user.id, digest(session), digest(csrf), ttl]
  );

  // Cookie untuk frontend dan backend lintas subdomain/domain.
  const cookieOptions = {
    secure: true,
    sameSite: 'none',
    maxAge: ttl * 3600_000
  };

  res.cookie('jalur_session', session, {
    ...cookieOptions,
    httpOnly: true,
    path: '/api'
  });

  res.cookie('jalur_csrf', csrf, {
    ...cookieOptions,
    httpOnly: false,
    path: '/'
  });

  res.json({
    user: {
      id: user.id,
      school_id: user.school_id,
      full_name: user.full_name,
      email: user.email,
      role: user.role
    },
    csrfToken: csrf
  });
}));

// AUTH LOGOUT
router.post('/auth/logout', asyncRoute(async (req, res) => {
  if (req.session?.id) {
    await pool.query(
      'DELETE FROM sessions WHERE id = $1',
      [req.session.id]
    );
  }

  res.clearCookie('jalur_session', {
    path: '/api',
    secure: true,
    sameSite: 'none'
  });

  res.clearCookie('jalur_csrf', {
    path: '/',
    secure: true,
    sameSite: 'none'
  });

  res.status(204).end();
}));

// AUTH ME
router.get('/auth/me', (req, res) => {
  if (!req.user) {
    return res.status(401).json({ error: 'unauthenticated' });
  }

  res.json({ user: req.user });
});

// CHANGE PASSWORD
router.post('/auth/change-password', asyncRoute(async (req, res) => {
  if (!req.user || !req.session) {
    return res.status(401).json({ error: 'unauthenticated' });
  }

  const p = z.object({
    current_password: z.string().min(1).max(200),
    new_password: z.string().min(14).max(200)
  }).safeParse(req.body);

  if (!p.success) {
    return res.status(400).json({
      error: 'invalid_input',
      message: 'Kata sandi baru minimal 14 karakter.'
    });
  }

  const u = await pool.query(
    'SELECT password_hash FROM users WHERE id = $1',
    [req.user.id]
  );

  if (
    !u.rows[0] ||
    !(await verifyPassword(p.data.current_password, u.rows[0].password_hash))
  ) {
    return res.status(401).json({ error: 'invalid_current_password' });
  }

  const hash = await hashPassword(p.data.new_password);

  await pool.query(
    'UPDATE users SET password_hash = $1, updated_at = now() WHERE id = $2',
    [hash, req.user.id]
  );

  await pool.query(
    'DELETE FROM sessions WHERE user_id = $1',
    [req.user.id]
  );

  res.clearCookie('jalur_session', { path: '/api', secure: true, sameSite: 'none' });
  res.clearCookie('jalur_csrf', { path: '/', secure: true, sameSite: 'none' });

  res.json({
    message: 'Kata sandi diperbarui. Silakan masuk kembali.'
  });
}));

// GRADES
router.get('/grades',
  requireRole(
    ROLES.STUDENT,
    ROLES.TEACHER,
    ROLES.SCHOOL_ADMIN,
    ROLES.PLATFORM_ADMIN
  ),
  asyncRoute(async (req, res) => {
    let sql;
    let params = [];

    if (req.user.role === ROLES.STUDENT) {
      sql = `SELECT id, subject_name, semester, academic_year,
                    score, notes, updated_at
             FROM grades
             WHERE student_id = $1
             ORDER BY academic_year DESC, semester, subject_name`;
      params = [req.user.id];
    } else if (req.user.role === ROLES.PLATFORM_ADMIN) {
      sql = `SELECT g.id, g.school_id, g.student_id, g.teacher_id,
                    g.class_id, g.subject_name, g.semester,
                    g.academic_year, g.score, g.notes, g.updated_at
             FROM grades g
             ORDER BY g.updated_at DESC LIMIT 1000`;
    } else if (req.user.role === ROLES.TEACHER) {
      sql = `SELECT g.id, g.student_id, g.teacher_id, g.class_id,
                    g.subject_name, g.semester, g.academic_year,
                    g.score, g.notes, g.updated_at
             FROM grades g
             JOIN teacher_assignments ta
               ON ta.teacher_id = $2
              AND ta.class_id = g.class_id
              AND ta.subject_name = g.subject_name
              AND ta.academic_year = g.academic_year
              AND ta.school_id = g.school_id
             WHERE g.school_id = $1
             ORDER BY g.updated_at DESC LIMIT 1000`;
      params = [req.user.school_id, req.user.id];
    } else {
      sql = `SELECT id, student_id, teacher_id, class_id,
                    subject_name, semester, academic_year,
                    score, notes, updated_at
             FROM grades
             WHERE school_id = $1
             ORDER BY updated_at DESC LIMIT 1000`;
      params = [req.user.school_id];
    }

    const { rows } = await pool.query(sql, params);
    res.json({ items: rows });
  })
);

const gradeSchema = z.object({
  student_id: z.string().uuid(),
  class_id: z.string().uuid(),
  subject_name: cleanText(120),
  semester: cleanText(30),
  academic_year: cleanText(20),
  score: z.number().min(0).max(100),
  notes: z.string().trim().max(1000).optional().nullable()
});

// CREATE / UPDATE GRADES
router.post('/grades',
  requireRole(ROLES.TEACHER, ROLES.SCHOOL_ADMIN),
  sameSchool,
  asyncRoute(async (req, res) => {
    const parsed = gradeSchema.safeParse(req.body);

    if (!parsed.success) {
      return res.status(400).json({
        error: 'invalid_input',
        details: parsed.error.flatten()
      });
    }

    const d = parsed.data;
    const client = await pool.connect();

    try {
      await client.query('BEGIN');

      const student = await client.query(
        `SELECT 1 FROM users
         WHERE id = $1 AND school_id = $2
         AND role = 'student' AND status = 'active'`,
        [d.student_id, req.user.school_id]
      );

      const cls = await client.query(
        'SELECT 1 FROM school_classes WHERE id = $1 AND school_id = $2',
        [d.class_id, req.user.school_id]
      );

      if (!student.rowCount || !cls.rowCount) {
        await client.query('ROLLBACK');
        return res.status(400).json({
          error: 'invalid_school_student_or_class'
        });
      }

      if (req.user.role === ROLES.TEACHER) {
        const assigned = await client.query(
          `SELECT 1 FROM teacher_assignments
           WHERE teacher_id = $1 AND class_id = $2
           AND subject_name = $3 AND academic_year = $4
           AND school_id = $5`,
          [
            req.user.id,
            d.class_id,
            d.subject_name,
            d.academic_year,
            req.user.school_id
          ]
        );

        if (!assigned.rowCount) {
          await client.query('ROLLBACK');
          return res.status(403).json({
            error: 'not_assigned_to_subject'
          });
        }
      }

      const result = await client.query(
        `INSERT INTO grades(
          school_id, student_id, teacher_id, class_id,
          subject_name, semester, academic_year, score, notes
        )
        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)
        ON CONFLICT(student_id, subject_name, semester, academic_year)
        DO UPDATE SET
          score = EXCLUDED.score,
          notes = EXCLUDED.notes,
          teacher_id = EXCLUDED.teacher_id,
          version = grades.version + 1,
          updated_at = now()
        WHERE grades.school_id = EXCLUDED.school_id
        RETURNING id, student_id, subject_name, semester,
                  academic_year, score, version, updated_at`,
        [
          req.user.school_id,
          d.student_id,
          req.user.id,
          d.class_id,
          d.subject_name,
          d.semester,
          d.academic_year,
          d.score,
          d.notes || null
        ]
      );

      if (!result.rowCount) {
        await client.query('ROLLBACK');
        return res.status(409).json({ error: 'grade_conflict' });
      }

      await client.query('COMMIT');

      await audit(req, 'grade.upsert', 'grade', result.rows[0].id);

      res.status(201).json({ item: result.rows[0] });
    } catch (e) {
      await client.query('ROLLBACK');
      throw e;
    } finally {
      client.release();
    }
  })
);

// BK APPOINTMENTS - STUDENT
router.post('/bk/appointments',
  requireRole(ROLES.STUDENT),
  asyncRoute(async (req, res) => {
    const p = z.object({
      requested_at: z.string().datetime({ offset: true }),
      mode: z.enum(['in_person', 'online']),
      topic: cleanText(120),
      student_note: z.string().trim().max(1000).optional()
    }).safeParse(req.body);

    if (!p.success) {
      return res.status(400).json({ error: 'invalid_input' });
    }

    if (!req.user.school_id) {
      return res.status(403).json({ error: 'school_scope_required' });
    }

    const { rows } = await pool.query(
      `INSERT INTO bk_appointments(
        school_id, student_id, requested_at, mode, topic, student_note
      )
      VALUES($1,$2,$3,$4,$5,$6)
      RETURNING id, requested_at, mode, topic, status, created_at`,
      [
        req.user.school_id,
        req.user.id,
        p.data.requested_at,
        p.data.mode,
        p.data.topic,
        p.data.student_note || null
      ]
    );

    await audit(req, 'bk_appointment.create', 'bk_appointment', rows[0].id);
    res.status(201).json({ item: rows[0] });
  })
);

// BK APPOINTMENTS - COUNSELOR
router.get('/bk/appointments',
  requireRole(ROLES.COUNSELOR, ROLES.SCHOOL_ADMIN),
  sameSchool,
  asyncRoute(async (req, res) => {
    const { rows } = await pool.query(
      `SELECT a.id, a.requested_at, a.mode, a.topic,
              a.student_note, a.status, a.created_at,
              u.full_name AS student_name,
              sp.student_number, sc.name AS class_name
       FROM bk_appointments a
       JOIN users u ON u.id = a.student_id
       LEFT JOIN student_profiles sp ON sp.user_id = u.id
       LEFT JOIN school_classes sc ON sc.id = sp.class_id
       WHERE a.school_id = $1
       ORDER BY a.requested_at ASC LIMIT 500`,
      [req.user.school_id]
    );

    res.json({ items: rows });
  })
);

router.patch('/bk/appointments/:id/status',
  requireRole(ROLES.COUNSELOR, ROLES.SCHOOL_ADMIN),
  sameSchool,
  asyncRoute(async (req, res) => {
    const p = z.object({
      status: z.enum([
        'pending',
        'confirmed',
        'reschedule_requested',
        'completed',
        'cancelled'
      ])
    }).safeParse(req.body);

    if (!p.success) {
      return res.status(400).json({ error: 'invalid_input' });
    }

    const { rows } = await pool.query(
      `UPDATE bk_appointments
       SET status = $1, counselor_id = $2, updated_at = now()
       WHERE id = $3 AND school_id = $4
       RETURNING id, status, requested_at`,
      [p.data.status, req.user.id, req.params.id, req.user.school_id]
    );

    if (!rows[0]) {
      return res.status(404).json({ error: 'not_found' });
    }

    await audit(req, 'bk_appointment.status', 'bk_appointment', req.params.id);
    res.json({ item: rows[0] });
  })
);

// ANONYMOUS VENTING
router.post('/anonymous-ventings', asyncRoute(async (req, res) => {
  const p = z.object({
    text: z.string().trim().min(3).max(3000),
    category: z.enum([
      'academic', 'family', 'friends', 'future', 'wellbeing', 'other'
    ])
  }).safeParse(req.body);

  if (!p.success) {
    return res.status(400).json({ error: 'invalid_input' });
  }

  const encrypted = encryptVenting(p.data.text);

  const { rows } = await pool.query(
    `INSERT INTO anonymous_ventings(
      encrypted_payload, nonce, auth_tag, broad_category
    )
    VALUES($1,$2,$3,$4)
    RETURNING id, received_day, status, broad_category`,
    [
      encrypted.encrypted_payload,
      encrypted.nonce,
      encrypted.auth_tag,
      p.data.category
    ]
  );

  res.status(201).json({
    item: {
      id: rows[0].id,
      received_day: rows[0].received_day,
      status: 'received',
      message: 'Curhat diterima tanpa mengaitkannya dengan akun.'
    }
  });
}));

router.get('/anonymous-ventings',
  requireRole(ROLES.WELLBEING_MODERATOR),
  asyncRoute(async (_req, res) => {
    const { rows } = await pool.query(
      `SELECT id, encrypted_payload, nonce, auth_tag,
              broad_category, received_day, status
       FROM anonymous_ventings
       WHERE status <> 'closed'
       ORDER BY received_day DESC LIMIT 200`
    );

    res.json({
      items: rows.map(r => ({
        id: r.id,
        text: decryptVenting(r),
        category: r.broad_category,
        received_day: r.received_day,
        status: r.status
      }))
    });
  })
);

router.patch('/anonymous-ventings/:id/status',
  requireRole(ROLES.WELLBEING_MODERATOR),
  asyncRoute(async (req, res) => {
    const p = z.object({
      status: z.enum([
        'unreviewed',
        'reviewed',
        'resource_shared',
        'closed'
      ])
    }).safeParse(req.body);

    if (!p.success) {
      return res.status(400).json({ error: 'invalid_input' });
    }

    const { rows } = await pool.query(
      `UPDATE anonymous_ventings
       SET status = $1
       WHERE id = $2
       RETURNING id, status, received_day`,
      [p.data.status, req.params.id]
    );

    if (!rows[0]) {
      return res.status(404).json({ error: 'not_found' });
    }

    res.json({ item: rows[0] });
  })
);

// SCHOOL CREATE USERS
router.post('/school/users',
  requireRole(ROLES.SCHOOL_ADMIN),
  sameSchool,
  asyncRoute(async (req, res) => {
    const p = z.object({
      email: z.string().email().max(254),
      full_name: cleanText(120),
      role: z.enum(['student', 'teacher', 'counselor']),
      temporary_password: z.string().min(14).max(200),
      student_number: z.string().trim().max(40).optional(),
      class_id: z.string().uuid().optional(),
      graduation_year: z.number().int().min(1950).max(2100).optional()
    }).safeParse(req.body);

    if (!p.success) {
      return res.status(400).json({
        error: 'invalid_input',
        details: p.error.flatten()
      });
    }

    const d = p.data;
    const client = await pool.connect();

    try {
      await client.query('BEGIN');

      if (d.role === 'student' && !d.student_number) {
        await client.query('ROLLBACK');
        return res.status(400).json({ error: 'student_number_required' });
      }

      if (d.class_id) {
        const c = await client.query(
          'SELECT 1 FROM school_classes WHERE id = $1 AND school_id = $2',
          [d.class_id, req.user.school_id]
        );

        if (!c.rowCount) {
          await client.query('ROLLBACK');
          return res.status(400).json({ error: 'invalid_class' });
        }
      }

      const pw = await hashPassword(d.temporary_password);

      const user = await client.query(
        `INSERT INTO users(
          school_id, email, full_name, password_hash, role, status
        )
        VALUES($1, lower($2), $3, $4, $5, 'active')
        RETURNING id, email, full_name, role, status`,
        [
          req.user.school_id,
          d.email,
          d.full_name,
          pw,
          d.role
        ]
      );

      if (d.role === 'student') {
        await client.query(
          `INSERT INTO student_profiles(
            user_id, school_id, student_number, class_id, graduation_year
          )
          VALUES($1,$2,$3,$4,$5)`,
          [
            user.rows[0].id,
            req.user.school_id,
            d.student_number,
            d.class_id || null,
            d.graduation_year || null
          ]
        );
      }

      await client.query('COMMIT');

      await audit(req, 'school_user.create', 'user', user.rows[0].id);

      res.status(201).json({
        item: user.rows[0],
        message: 'Akun berhasil dibuat.'
      });
    } catch (e) {
      await client.query('ROLLBACK');

      if (e.code === '23505') {
        return res.status(409).json({
          error: 'email_or_student_number_exists'
        });
      }

      throw e;
    } finally {
      client.release();
    }
  })
);

// SCHOOL CLASSES
router.post('/school/classes',
  requireRole(ROLES.SCHOOL_ADMIN),
  sameSchool,
  asyncRoute(async (req, res) => {
    const p = z.object({
      name: cleanText(80),
      academic_year: z.string().trim().min(4).max(20)
    }).safeParse(req.body);

    if (!p.success) {
      return res.status(400).json({ error: 'invalid_input' });
    }

    const { rows } = await pool.query(
      `INSERT INTO school_classes(school_id, name, academic_year)
       VALUES($1,$2,$3)
       ON CONFLICT(school_id, name, academic_year) DO NOTHING
       RETURNING id, name, academic_year`,
      [req.user.school_id, p.data.name, p.data.academic_year]
    );

    if (!rows[0]) {
      return res.status(409).json({ error: 'class_exists' });
    }

    await audit(req, 'school_class.create', 'school_class', rows[0].id);
    res.status(201).json({ item: rows[0] });
  })
);

// SCHOOL TEACHER ASSIGNMENTS
router.post('/school/teacher-assignments',
  requireRole(ROLES.SCHOOL_ADMIN),
  sameSchool,
  asyncRoute(async (req, res) => {
    const p = z.object({
      teacher_id: z.string().uuid(),
      class_id: z.string().uuid(),
      subject_name: cleanText(120),
      academic_year: cleanText(20)
    }).safeParse(req.body);

    if (!p.success) {
      return res.status(400).json({ error: 'invalid_input' });
    }

    const d = p.data;

    const t = await pool.query(
      `SELECT 1 FROM users
       WHERE id = $1 AND school_id = $2
       AND role = 'teacher' AND status = 'active'`,
      [d.teacher_id, req.user.school_id]
    );

    const c = await pool.query(
      'SELECT 1 FROM school_classes WHERE id = $1 AND school_id = $2',
      [d.class_id, req.user.school_id]
    );

    if (!t.rowCount || !c.rowCount) {
      return res.status(400).json({ error: 'teacher_or_class_invalid' });
    }

    const { rows } = await pool.query(
      `INSERT INTO teacher_assignments(
        school_id, teacher_id, class_id, subject_name, academic_year
      )
      VALUES($1,$2,$3,$4,$5)
      ON CONFLICT(teacher_id, class_id, subject_name, academic_year)
      DO NOTHING
      RETURNING id, teacher_id, class_id, subject_name, academic_year`,
      [
        req.user.school_id,
        d.teacher_id,
        d.class_id,
        d.subject_name,
        d.academic_year
      ]
    );

    if (!rows[0]) {
      return res.status(409).json({ error: 'assignment_exists' });
    }

    await audit(req, 'teacher_assignment.create', 'teacher_assignment', rows[0].id);
    res.status(201).json({ item: rows[0] });
  })
);

// SCHOOL STUDENTS
router.get('/school/students',
  requireRole(ROLES.SCHOOL_ADMIN, ROLES.COUNSELOR, ROLES.TEACHER),
  sameSchool,
  asyncRoute(async (req, res) => {
    const { rows } = await pool.query(
      `SELECT u.id, u.full_name, u.email,
              sp.student_number, sp.graduation_year,
              c.name AS class_name
       FROM users u
       JOIN student_profiles sp ON sp.user_id = u.id
       LEFT JOIN school_classes c ON c.id = sp.class_id
       WHERE u.school_id = $1 AND u.role = 'student'
       ORDER BY u.full_name LIMIT 1000`,
      [req.user.school_id]
    );

    res.json({ items: rows });
  })
);

// SCHOOL ALUMNI
router.get('/school/alumni',
  requireRole(ROLES.SCHOOL_ADMIN),
  sameSchool,
  asyncRoute(async (req, res) => {
    const { rows } = await pool.query(
      `SELECT id, full_name, graduation_year, next_step,
              institution, program, consent_to_share
       FROM alumni_profiles
       WHERE school_id = $1
       ORDER BY graduation_year DESC, full_name LIMIT 1000`,
      [req.user.school_id]
    );

    res.json({ items: rows });
  })
);

router.post('/school/alumni',
  requireRole(ROLES.SCHOOL_ADMIN),
  sameSchool,
  asyncRoute(async (req, res) => {
    const p = z.object({
      full_name: cleanText(120),
      graduation_year: z.number().int().min(1950).max(2100),
      next_step: z.string().trim().max(120).optional(),
      institution: z.string().trim().max(180).optional(),
      program: z.string().trim().max(180).optional(),
      consent_to_share: z.boolean().default(false)
    }).safeParse(req.body);

    if (!p.success) {
      return res.status(400).json({
        error: 'invalid_input',
        details: p.error.flatten()
      });
    }

    const d = p.data;

    const { rows } = await pool.query(
      `INSERT INTO alumni_profiles(
        school_id, full_name, graduation_year,
        next_step, institution, program, consent_to_share
      )
      VALUES($1,$2,$3,$4,$5,$6,$7)
      RETURNING id, full_name, graduation_year,
                next_step, institution, program, consent_to_share`,
      [
        req.user.school_id,
        d.full_name,
        d.graduation_year,
        d.next_step || null,
        d.institution || null,
        d.program || null,
        d.consent_to_share
      ]
    );

    await audit(req, 'alumni.create', 'alumni', rows[0].id);
    res.status(201).json({ item: rows[0] });
  })
);
