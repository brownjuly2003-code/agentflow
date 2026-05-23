-- Seed each per-branch fan-out database with a small synthetic OLTP set.
-- Keep it minimal (~10 customers + ~30 orders per branch) — the fan-out
-- proof is "rows in PG land in the per-branch CH DB", not row count.
--
-- Apply with:
--   kubectl exec -i -n dv2 postgres-0 -- psql -U ops -d postgres \
--     < warehouse/agentflow/dv2/postgres_oltp/fanout/02_seed.sql

\c ops_msk_db

INSERT INTO customers (customer_id, first_name, last_name, email, phone) VALUES
  ('msk-c-001', 'Alexei', 'Volkov',  'volkov@example.ru',  '+74951110001'),
  ('msk-c-002', 'Maria',  'Sokolova','sokolova@example.ru','+74951110002'),
  ('msk-c-003', 'Dmitry', 'Ivanov',  'ivanov@example.ru',  '+74951110003'),
  ('msk-c-004', 'Olga',   'Smirnova','smirnova@example.ru','+74951110004'),
  ('msk-c-005', 'Sergei', 'Popov',   'popov@example.ru',   '+74951110005'),
  ('msk-c-006', 'Anna',   'Kuznetsova','kuznetsova@example.ru','+74951110006'),
  ('msk-c-007', 'Pavel',  'Lebedev', 'lebedev@example.ru', '+74951110007'),
  ('msk-c-008', 'Elena',  'Morozova','morozova@example.ru','+74951110008'),
  ('msk-c-009', 'Mikhail','Novikov', 'novikov@example.ru', '+74951110009'),
  ('msk-c-010', 'Tatiana','Fedorova','fedorova@example.ru','+74951110010')
ON CONFLICT (customer_id) DO NOTHING;

INSERT INTO orders (order_id, customer_id, status, total, currency) VALUES
  ('msk-o-001','msk-c-001','paid',     4500.00,'RUB'),
  ('msk-o-002','msk-c-001','paid',     2100.00,'RUB'),
  ('msk-o-003','msk-c-002','paid',     8900.00,'RUB'),
  ('msk-o-004','msk-c-003','pending',  1200.00,'RUB'),
  ('msk-o-005','msk-c-003','paid',     6700.00,'RUB'),
  ('msk-o-006','msk-c-004','paid',     3300.00,'RUB'),
  ('msk-o-007','msk-c-004','refunded', 1850.00,'RUB'),
  ('msk-o-008','msk-c-005','paid',    12500.00,'RUB'),
  ('msk-o-009','msk-c-005','paid',     2400.00,'RUB'),
  ('msk-o-010','msk-c-006','pending',  5600.00,'RUB'),
  ('msk-o-011','msk-c-006','paid',     7800.00,'RUB'),
  ('msk-o-012','msk-c-007','paid',     1900.00,'RUB'),
  ('msk-o-013','msk-c-007','paid',    15300.00,'RUB'),
  ('msk-o-014','msk-c-008','paid',     4100.00,'RUB'),
  ('msk-o-015','msk-c-008','paid',     6200.00,'RUB'),
  ('msk-o-016','msk-c-009','paid',     2700.00,'RUB'),
  ('msk-o-017','msk-c-009','pending',  3400.00,'RUB'),
  ('msk-o-018','msk-c-009','paid',     8100.00,'RUB'),
  ('msk-o-019','msk-c-010','paid',     1100.00,'RUB'),
  ('msk-o-020','msk-c-010','paid',     9300.00,'RUB'),
  ('msk-o-021','msk-c-010','paid',     5700.00,'RUB'),
  ('msk-o-022','msk-c-001','paid',     3800.00,'RUB'),
  ('msk-o-023','msk-c-002','paid',     7400.00,'RUB'),
  ('msk-o-024','msk-c-003','paid',     2900.00,'RUB'),
  ('msk-o-025','msk-c-005','paid',    11200.00,'RUB'),
  ('msk-o-026','msk-c-007','paid',     4600.00,'RUB'),
  ('msk-o-027','msk-c-008','paid',     8500.00,'RUB'),
  ('msk-o-028','msk-c-009','paid',     3100.00,'RUB'),
  ('msk-o-029','msk-c-010','paid',     6900.00,'RUB'),
  ('msk-o-030','msk-c-004','paid',     2200.00,'RUB')
ON CONFLICT (order_id) DO NOTHING;

\c ops_dxb_db

INSERT INTO customers (customer_id, first_name, last_name, email, phone) VALUES
  ('dxb-c-001','Khalid', 'Al-Maktoum','khalid@example.ae','+97150100001'),
  ('dxb-c-002','Fatima', 'Al-Nahyan', 'fatima@example.ae','+97150100002'),
  ('dxb-c-003','Omar',   'Al-Sayegh', 'omar@example.ae',  '+97150100003'),
  ('dxb-c-004','Layla',  'Al-Marri',  'layla@example.ae', '+97150100004'),
  ('dxb-c-005','Hassan', 'Al-Falasi', 'hassan@example.ae','+97150100005'),
  ('dxb-c-006','Noura',  'Al-Mansouri','noura@example.ae','+97150100006'),
  ('dxb-c-007','Yusuf',  'Al-Owais',  'yusuf@example.ae', '+97150100007'),
  ('dxb-c-008','Mariam', 'Al-Suwaidi','mariam@example.ae','+97150100008')
ON CONFLICT (customer_id) DO NOTHING;

INSERT INTO orders (order_id, customer_id, status, total, currency) VALUES
  ('dxb-o-001','dxb-c-001','paid',     850.00,'AED'),
  ('dxb-o-002','dxb-c-001','paid',    1240.00,'AED'),
  ('dxb-o-003','dxb-c-002','paid',     420.00,'AED'),
  ('dxb-o-004','dxb-c-003','paid',    2300.00,'AED'),
  ('dxb-o-005','dxb-c-003','pending',  680.00,'AED'),
  ('dxb-o-006','dxb-c-004','paid',    1100.00,'AED'),
  ('dxb-o-007','dxb-c-005','paid',    1850.00,'AED'),
  ('dxb-o-008','dxb-c-005','paid',     590.00,'AED'),
  ('dxb-o-009','dxb-c-006','paid',     920.00,'AED'),
  ('dxb-o-010','dxb-c-006','refunded', 380.00,'AED'),
  ('dxb-o-011','dxb-c-007','paid',    2700.00,'AED'),
  ('dxb-o-012','dxb-c-007','paid',     750.00,'AED'),
  ('dxb-o-013','dxb-c-008','paid',    1450.00,'AED'),
  ('dxb-o-014','dxb-c-008','paid',     980.00,'AED'),
  ('dxb-o-015','dxb-c-001','paid',     310.00,'AED'),
  ('dxb-o-016','dxb-c-002','paid',    1670.00,'AED'),
  ('dxb-o-017','dxb-c-003','paid',     820.00,'AED'),
  ('dxb-o-018','dxb-c-004','paid',    2150.00,'AED'),
  ('dxb-o-019','dxb-c-005','paid',     460.00,'AED'),
  ('dxb-o-020','dxb-c-006','paid',    1320.00,'AED')
ON CONFLICT (order_id) DO NOTHING;
