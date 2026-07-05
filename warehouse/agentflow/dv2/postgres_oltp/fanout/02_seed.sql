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

-- Status vocabulary = generator-spec.md §2 ladder (pending / confirmed /
-- shipped / delivered / cancelled). msk amounts sit in the marketplace/d2c
-- retail bands (1.5k-5k ₽) with a few b2b tickets (30k-80k ₽); none fall in
-- the 10k-25k bimodality dead-zone (§12 #4).
INSERT INTO orders (order_id, customer_id, status, total, currency) VALUES
  ('msk-o-001','msk-c-001','delivered', 2450.00,'RUB'),
  ('msk-o-002','msk-c-001','delivered', 2100.00,'RUB'),
  ('msk-o-003','msk-c-002','shipped',   2890.00,'RUB'),
  ('msk-o-004','msk-c-003','pending',   1650.00,'RUB'),
  ('msk-o-005','msk-c-003','delivered', 3300.00,'RUB'),
  ('msk-o-006','msk-c-004','delivered', 2750.00,'RUB'),
  ('msk-o-007','msk-c-004','cancelled', 1850.00,'RUB'),
  ('msk-o-008','msk-c-005','delivered',42000.00,'RUB'),
  ('msk-o-009','msk-c-005','delivered', 2400.00,'RUB'),
  ('msk-o-010','msk-c-006','pending',   4600.00,'RUB'),
  ('msk-o-011','msk-c-006','confirmed', 3800.00,'RUB'),
  ('msk-o-012','msk-c-007','delivered', 1900.00,'RUB'),
  ('msk-o-013','msk-c-007','delivered',58000.00,'RUB'),
  ('msk-o-014','msk-c-008','delivered', 2650.00,'RUB'),
  ('msk-o-015','msk-c-008','shipped',   4200.00,'RUB'),
  ('msk-o-016','msk-c-009','delivered', 2700.00,'RUB'),
  ('msk-o-017','msk-c-009','pending',   3400.00,'RUB'),
  ('msk-o-018','msk-c-009','delivered', 2950.00,'RUB'),
  ('msk-o-019','msk-c-010','delivered', 1600.00,'RUB'),
  ('msk-o-020','msk-c-010','delivered', 4700.00,'RUB'),
  ('msk-o-021','msk-c-010','delivered', 3900.00,'RUB'),
  ('msk-o-022','msk-c-001','delivered', 2200.00,'RUB'),
  ('msk-o-023','msk-c-002','shipped',   4400.00,'RUB'),
  ('msk-o-024','msk-c-003','delivered', 2900.00,'RUB'),
  ('msk-o-025','msk-c-005','delivered',71000.00,'RUB'),
  ('msk-o-026','msk-c-007','delivered', 3600.00,'RUB'),
  ('msk-o-027','msk-c-008','confirmed', 4850.00,'RUB'),
  ('msk-o-028','msk-c-009','delivered', 3100.00,'RUB'),
  ('msk-o-029','msk-c-010','delivered', 4900.00,'RUB'),
  ('msk-o-030','msk-c-004','delivered', 2200.00,'RUB')
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

-- dxb is the b2b re-export branch (§1): every order is wholesale, priced in
-- AED at the export-pallet scale (≈ 2.5k-5.1k AED ≈ 60k-125k ₽ at the §10 FX
-- of 24.5 ₽/AED). §2 status ladder; no retail-scale tickets.
INSERT INTO orders (order_id, customer_id, status, total, currency) VALUES
  ('dxb-o-001','dxb-c-001','delivered', 3200.00,'AED'),
  ('dxb-o-002','dxb-c-001','delivered', 4100.00,'AED'),
  ('dxb-o-003','dxb-c-002','shipped',   2800.00,'AED'),
  ('dxb-o-004','dxb-c-003','delivered', 4600.00,'AED'),
  ('dxb-o-005','dxb-c-003','pending',   2500.00,'AED'),
  ('dxb-o-006','dxb-c-004','delivered', 3400.00,'AED'),
  ('dxb-o-007','dxb-c-005','delivered', 4900.00,'AED'),
  ('dxb-o-008','dxb-c-005','delivered', 2650.00,'AED'),
  ('dxb-o-009','dxb-c-006','delivered', 3700.00,'AED'),
  ('dxb-o-010','dxb-c-006','cancelled', 2450.00,'AED'),
  ('dxb-o-011','dxb-c-007','delivered', 5100.00,'AED'),
  ('dxb-o-012','dxb-c-007','delivered', 2900.00,'AED'),
  ('dxb-o-013','dxb-c-008','shipped',   4300.00,'AED'),
  ('dxb-o-014','dxb-c-008','delivered', 3550.00,'AED'),
  ('dxb-o-015','dxb-c-001','delivered', 2750.00,'AED'),
  ('dxb-o-016','dxb-c-002','delivered', 4750.00,'AED'),
  ('dxb-o-017','dxb-c-003','confirmed', 3150.00,'AED'),
  ('dxb-o-018','dxb-c-004','delivered', 4400.00,'AED'),
  ('dxb-o-019','dxb-c-005','delivered', 2600.00,'AED'),
  ('dxb-o-020','dxb-c-006','delivered', 3900.00,'AED')
ON CONFLICT (order_id) DO NOTHING;
