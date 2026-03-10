USE language_learning;

-- 1) Jezici (bez dupliranja)
INSERT IGNORE INTO languages (code, name) VALUES
('en', 'English'),
('de', 'Deutsch');

-- 2) Korisnici: ADMIN / TEACHER / STUDENT
-- Upis je "idempotentan": ako već postoji email, ažuriraće hash/role/display_name.
INSERT INTO users (email, password_hash, role_id, display_name, is_active)
VALUES
(
  'admin@test.com',
  'scrypt:32768:8:1$4mASPxtDKUw7Vwyi$ac925177797f84462a86b474bdb4f4a3aa595a2ff5332c578dc96fa8685cfd02468af0635d1f1ca20b168913466ce8fddae4fa3d5f55badedb5adaae78e45afe',
  (SELECT id FROM roles WHERE name='ADMIN'),
  'Admin',
  1
),
(
  'teacher@test.com',
  'scrypt:32768:8:1$yN5fi6fo6R1J0tBS$e865b90bbf6da40179987b531fe54f2ba6b045bb649c8a3c14329fd9d65e7d646c3dea2143028f2591b89dfcf1d2fab80385a9ddd41e3aebb893e5371d2e6852',
  (SELECT id FROM roles WHERE name='TEACHER'),
  'Teacher',
  1
),
(
  'student@test.com',
  'scrypt:32768:8:1$YK3kDDZZ0LoiqXMv$f0f86c2898608af096e32df73217f63dee58f6a8ad3eff229155ad4945b39d393849c2e274595e0467176d52757cb042d06f094f760d33c905b77d0ef938d408',
  (SELECT id FROM roles WHERE name='STUDENT'),
  'Student',
  1
)
ON DUPLICATE KEY UPDATE
  password_hash = VALUES(password_hash),
  role_id = VALUES(role_id),
  display_name = VALUES(display_name),
  is_active = VALUES(is_active);

-- 3) Primer lekcija
INSERT INTO lessons (language_id, level, title, content_html, order_no, created_by)
VALUES
(
  (SELECT id FROM languages WHERE code='en'),
  'A1',
  'Greetings',
  '<h3>Greetings</h3><p>Hello! My name is...</p>',
  1,
  (SELECT id FROM users WHERE email='admin@test.com')
),
(
  (SELECT id FROM languages WHERE code='en'),
  'A1',
  'Numbers',
  '<h3>Numbers</h3><p>one, two, three...</p>',
  2,
  (SELECT id FROM users WHERE email='admin@test.com')
),
(
  (SELECT id FROM languages WHERE code='de'),
  'A1',
  'Begrüßung',
  '<h3>Begrüßung</h3><p>Hallo! Ich heiße...</p>',
  1,
  (SELECT id FROM users WHERE email='admin@test.com')
);