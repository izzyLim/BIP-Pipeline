-- Oracle 19c 테스트용 샘플 데이터
-- PDB(ORCLPDB1)에서 실행

-- 1. 테스트 사용자 생성
ALTER SESSION SET CONTAINER = ORCLPDB1;
CREATE USER testuser IDENTIFIED BY TestPass123;
GRANT CONNECT, RESOURCE TO testuser;
GRANT CREATE VIEW TO testuser;
GRANT UNLIMITED TABLESPACE TO testuser;
ALTER USER testuser QUOTA UNLIMITED ON USERS;

-- 2. 테스트 테이블 생성 (사내 업무 데이터 시뮬레이션)
CONNECT testuser/TestPass123@//localhost:1521/ORCLPDB1

-- 부서
CREATE TABLE departments (
    dept_id NUMBER PRIMARY KEY,
    dept_name VARCHAR2(100) NOT NULL,
    manager_name VARCHAR2(100),
    created_at TIMESTAMP DEFAULT SYSTIMESTAMP
);

-- 직원
CREATE TABLE employees (
    emp_id NUMBER PRIMARY KEY,
    emp_name VARCHAR2(100) NOT NULL,
    dept_id NUMBER REFERENCES departments(dept_id),
    position VARCHAR2(50),
    salary NUMBER(12,2),
    hire_date DATE,
    is_active NUMBER(1) DEFAULT 1
);

-- 매출
CREATE TABLE sales (
    sale_id NUMBER PRIMARY KEY,
    sale_date DATE NOT NULL,
    dept_id NUMBER REFERENCES departments(dept_id),
    product_name VARCHAR2(200),
    category VARCHAR2(100),
    quantity NUMBER,
    unit_price NUMBER(12,2),
    total_amount NUMBER(14,2),
    customer_name VARCHAR2(200),
    region VARCHAR2(50)
);

-- 월별 KPI
CREATE TABLE monthly_kpi (
    kpi_id NUMBER PRIMARY KEY,
    dept_id NUMBER REFERENCES departments(dept_id),
    kpi_month DATE NOT NULL,
    revenue NUMBER(14,2),
    cost NUMBER(14,2),
    profit NUMBER(14,2),
    headcount NUMBER,
    customer_count NUMBER,
    satisfaction_score NUMBER(3,1)
);

-- 3. 샘플 데이터 삽입

-- 부서
INSERT INTO departments VALUES (1, '영업1팀', '김철수', SYSTIMESTAMP);
INSERT INTO departments VALUES (2, '영업2팀', '이영희', SYSTIMESTAMP);
INSERT INTO departments VALUES (3, '개발팀', '박지성', SYSTIMESTAMP);
INSERT INTO departments VALUES (4, '마케팅팀', '최유진', SYSTIMESTAMP);
INSERT INTO departments VALUES (5, '인사팀', '정민수', SYSTIMESTAMP);

-- 직원
INSERT INTO employees VALUES (101, '김철수', 1, '팀장', 8500000, DATE '2018-03-15', 1);
INSERT INTO employees VALUES (102, '홍길동', 1, '대리', 4500000, DATE '2021-07-01', 1);
INSERT INTO employees VALUES (103, '이영희', 2, '팀장', 8200000, DATE '2017-09-01', 1);
INSERT INTO employees VALUES (104, '박지성', 3, '팀장', 9000000, DATE '2016-01-15', 1);
INSERT INTO employees VALUES (105, '최유진', 4, '팀장', 7800000, DATE '2019-06-01', 1);
INSERT INTO employees VALUES (106, '정민수', 5, '팀장', 7500000, DATE '2020-02-01', 1);
INSERT INTO employees VALUES (107, '강호동', 1, '사원', 3800000, DATE '2023-03-01', 1);
INSERT INTO employees VALUES (108, '유재석', 2, '과장', 5500000, DATE '2020-04-15', 1);
INSERT INTO employees VALUES (109, '송중기', 3, '선임', 5800000, DATE '2021-01-10', 1);
INSERT INTO employees VALUES (110, '김태희', 4, '대리', 4200000, DATE '2022-08-01', 1);

-- 매출 (최근 6개월)
INSERT INTO sales VALUES (1, DATE '2026-01-15', 1, '솔루션A', 'SW', 5, 20000000, 100000000, '삼성전자', '서울');
INSERT INTO sales VALUES (2, DATE '2026-01-20', 1, '솔루션B', 'SW', 3, 15000000, 45000000, 'LG전자', '서울');
INSERT INTO sales VALUES (3, DATE '2026-02-10', 2, '컨설팅', '서비스', 1, 80000000, 80000000, 'SK하이닉스', '경기');
INSERT INTO sales VALUES (4, DATE '2026-02-15', 1, '솔루션A', 'SW', 2, 20000000, 40000000, '현대차', '서울');
INSERT INTO sales VALUES (5, DATE '2026-03-01', 2, '솔루션C', 'HW', 10, 5000000, 50000000, '카카오', '제주');
INSERT INTO sales VALUES (6, DATE '2026-03-10', 1, '솔루션A', 'SW', 8, 20000000, 160000000, 'NAVER', '경기');
INSERT INTO sales VALUES (7, DATE '2026-03-20', 3, '개발용역', '서비스', 1, 150000000, 150000000, '삼성SDS', '서울');
INSERT INTO sales VALUES (8, DATE '2026-04-01', 2, '컨설팅', '서비스', 2, 60000000, 120000000, 'KT', '서울');
INSERT INTO sales VALUES (9, DATE '2026-04-05', 1, '솔루션B', 'SW', 5, 15000000, 75000000, 'LG CNS', '서울');
INSERT INTO sales VALUES (10, DATE '2026-04-10', 4, '광고패키지', '마케팅', 1, 30000000, 30000000, '쿠팡', '서울');

-- 월별 KPI
INSERT INTO monthly_kpi VALUES (1, 1, DATE '2026-01-01', 145000000, 95000000, 50000000, 3, 5, 4.2);
INSERT INTO monthly_kpi VALUES (2, 2, DATE '2026-01-01', 80000000, 60000000, 20000000, 2, 3, 3.8);
INSERT INTO monthly_kpi VALUES (3, 3, DATE '2026-01-01', 0, 45000000, -45000000, 3, 0, NULL);
INSERT INTO monthly_kpi VALUES (4, 4, DATE '2026-01-01', 30000000, 25000000, 5000000, 2, 8, 4.0);
INSERT INTO monthly_kpi VALUES (5, 1, DATE '2026-02-01', 40000000, 30000000, 10000000, 3, 2, 4.5);
INSERT INTO monthly_kpi VALUES (6, 2, DATE '2026-02-01', 130000000, 70000000, 60000000, 2, 4, 4.1);
INSERT INTO monthly_kpi VALUES (7, 3, DATE '2026-02-01', 150000000, 80000000, 70000000, 3, 1, 4.8);
INSERT INTO monthly_kpi VALUES (8, 4, DATE '2026-02-01', 20000000, 18000000, 2000000, 2, 5, 3.5);
INSERT INTO monthly_kpi VALUES (9, 1, DATE '2026-03-01', 200000000, 100000000, 100000000, 3, 6, 4.7);
INSERT INTO monthly_kpi VALUES (10, 2, DATE '2026-03-01', 50000000, 40000000, 10000000, 2, 3, 3.9);
INSERT INTO monthly_kpi VALUES (11, 3, DATE '2026-03-01', 0, 50000000, -50000000, 3, 0, NULL);
INSERT INTO monthly_kpi VALUES (12, 4, DATE '2026-03-01', 30000000, 20000000, 10000000, 2, 10, 4.3);

COMMIT;

-- 4. Gold View (BIP 패턴 적용)
CREATE OR REPLACE VIEW v_sales_summary AS
SELECT
    s.sale_date,
    d.dept_name,
    s.product_name,
    s.category,
    s.quantity,
    s.unit_price,
    s.total_amount,
    s.customer_name,
    s.region,
    CASE WHEN s.total_amount >= 100000000 THEN 'Y' ELSE 'N' END AS is_large_deal,
    CASE WHEN s.category = 'SW' THEN 'Y' ELSE 'N' END AS is_software
FROM sales s
JOIN departments d ON s.dept_id = d.dept_id;

CREATE OR REPLACE VIEW v_dept_monthly_performance AS
SELECT
    k.kpi_month,
    d.dept_name,
    k.revenue,
    k.cost,
    k.profit,
    k.headcount,
    k.customer_count,
    k.satisfaction_score,
    CASE WHEN k.profit > 0 THEN 'Y' ELSE 'N' END AS is_profitable,
    CASE WHEN k.satisfaction_score >= 4.0 THEN 'Y' ELSE 'N' END AS is_high_satisfaction,
    ROUND(k.profit / NULLIF(k.revenue, 0) * 100, 1) AS profit_margin_pct
FROM monthly_kpi k
JOIN departments d ON k.dept_id = d.dept_id;
