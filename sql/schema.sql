PRAGMA foreign_keys = ON;

CREATE TABLE branch_info (
    branch_id TEXT PRIMARY KEY,
    branch_name TEXT NOT NULL,
    branch_level TEXT NOT NULL CHECK (branch_level IN ('HEAD', 'TIER1', 'TIER2')),
    parent_branch_id TEXT,
    region_name TEXT NOT NULL,
    province_name TEXT NOT NULL,
    city_name TEXT NOT NULL,
    open_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'CLOSED')),
    FOREIGN KEY (parent_branch_id) REFERENCES branch_info(branch_id)
);

CREATE TABLE customer_manager (
    manager_id TEXT PRIMARY KEY,
    manager_name TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    hire_date DATE NOT NULL,
    manager_level TEXT NOT NULL CHECK (manager_level IN ('JUNIOR', 'MIDDLE', 'SENIOR')),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE')),
    FOREIGN KEY (branch_id) REFERENCES branch_info(branch_id)
);

CREATE TABLE customer_info (
    customer_id TEXT PRIMARY KEY,
    gender TEXT CHECK (gender IN ('M', 'F', 'U')),
    birth_year INTEGER CHECK (birth_year BETWEEN 1920 AND 2010),
    province_name TEXT NOT NULL,
    city_tier TEXT NOT NULL CHECK (city_tier IN ('T1', 'NEW_T1', 'T2', 'T3_PLUS')),
    occupation_type TEXT NOT NULL,
    customer_level TEXT NOT NULL CHECK (customer_level IN ('MASS', 'AFFLUENT', 'HNW')),
    risk_preference TEXT NOT NULL CHECK (risk_preference IN ('C1', 'C2', 'C3', 'C4', 'C5')),
    register_date DATE NOT NULL,
    branch_id TEXT NOT NULL,
    manager_id TEXT,
    customer_status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (customer_status IN ('ACTIVE', 'DORMANT', 'CLOSED')),
    FOREIGN KEY (branch_id) REFERENCES branch_info(branch_id),
    FOREIGN KEY (manager_id) REFERENCES customer_manager(manager_id)
);

CREATE TABLE account_info (
    account_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK (account_type IN ('CURRENT', 'TIME', 'WEALTH_CASH')),
    currency_code TEXT NOT NULL DEFAULT 'CNY',
    open_date DATE NOT NULL,
    close_date DATE,
    current_balance NUMERIC NOT NULL DEFAULT 0 CHECK (current_balance >= 0),
    account_status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (account_status IN ('ACTIVE', 'FROZEN', 'CLOSED')),
    FOREIGN KEY (customer_id) REFERENCES customer_info(customer_id),
    FOREIGN KEY (branch_id) REFERENCES branch_info(branch_id),
    CHECK (close_date IS NULL OR close_date >= open_date)
);

CREATE TABLE transaction_detail (
    transaction_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    transaction_time DATETIME NOT NULL,
    transaction_type TEXT NOT NULL CHECK (transaction_type IN ('DEPOSIT', 'WITHDRAW', 'TRANSFER_IN', 'TRANSFER_OUT', 'PAYMENT')),
    direction TEXT NOT NULL CHECK (direction IN ('IN', 'OUT')),
    amount NUMERIC NOT NULL CHECK (amount > 0),
    channel_type TEXT NOT NULL CHECK (channel_type IN ('APP', 'WEB', 'COUNTER', 'ATM', 'THIRD_PARTY')),
    transaction_status TEXT NOT NULL CHECK (transaction_status IN ('SUCCESS', 'FAILED', 'REVERSED')),
    is_abnormal INTEGER NOT NULL DEFAULT 0 CHECK (is_abnormal IN (0, 1)),
    FOREIGN KEY (account_id) REFERENCES account_info(account_id),
    FOREIGN KEY (customer_id) REFERENCES customer_info(customer_id),
    FOREIGN KEY (branch_id) REFERENCES branch_info(branch_id)
);

CREATE TABLE loan_info (
    loan_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    manager_id TEXT,
    loan_type TEXT NOT NULL CHECK (loan_type IN ('MORTGAGE', 'CONSUMER', 'BUSINESS')),
    issue_date DATE NOT NULL,
    maturity_date DATE NOT NULL,
    original_amount NUMERIC NOT NULL CHECK (original_amount > 0),
    outstanding_balance NUMERIC NOT NULL CHECK (outstanding_balance >= 0),
    annual_rate NUMERIC NOT NULL CHECK (annual_rate >= 0),
    overdue_days INTEGER NOT NULL DEFAULT 0 CHECK (overdue_days >= 0),
    overdue_amount NUMERIC NOT NULL DEFAULT 0 CHECK (overdue_amount >= 0),
    five_classification TEXT NOT NULL CHECK (five_classification IN ('NORMAL', 'SPECIAL_MENTION', 'SUBSTANDARD', 'DOUBTFUL', 'LOSS')),
    loan_status TEXT NOT NULL CHECK (loan_status IN ('ACTIVE', 'SETTLED', 'DEFAULTED')),
    FOREIGN KEY (customer_id) REFERENCES customer_info(customer_id),
    FOREIGN KEY (branch_id) REFERENCES branch_info(branch_id),
    FOREIGN KEY (manager_id) REFERENCES customer_manager(manager_id),
    CHECK (maturity_date > issue_date),
    CHECK (outstanding_balance <= original_amount),
    CHECK (overdue_amount <= outstanding_balance)
);

CREATE TABLE wealth_product (
    product_id TEXT PRIMARY KEY,
    product_name TEXT NOT NULL,
    product_category TEXT NOT NULL CHECK (product_category IN ('FIXED_INCOME', 'MIXED', 'EQUITY', 'CASH_MANAGEMENT')),
    risk_level TEXT NOT NULL CHECK (risk_level IN ('R1', 'R2', 'R3', 'R4', 'R5')),
    term_days INTEGER NOT NULL CHECK (term_days > 0),
    expected_annual_return NUMERIC CHECK (expected_annual_return >= 0),
    launch_date DATE NOT NULL,
    end_date DATE,
    product_status TEXT NOT NULL CHECK (product_status IN ('ON_SALE', 'CLOSED', 'MATURED')),
    CHECK (end_date IS NULL OR end_date >= launch_date)
);

CREATE TABLE product_purchase (
    purchase_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    manager_id TEXT,
    purchase_date DATE NOT NULL,
    purchase_amount NUMERIC NOT NULL CHECK (purchase_amount > 0),
    maturity_date DATE NOT NULL,
    holding_amount NUMERIC NOT NULL CHECK (holding_amount >= 0),
    purchase_channel TEXT NOT NULL CHECK (purchase_channel IN ('APP', 'WEB', 'COUNTER')),
    purchase_status TEXT NOT NULL CHECK (purchase_status IN ('HOLDING', 'REDEEMED', 'MATURED')),
    FOREIGN KEY (product_id) REFERENCES wealth_product(product_id),
    FOREIGN KEY (customer_id) REFERENCES customer_info(customer_id),
    FOREIGN KEY (branch_id) REFERENCES branch_info(branch_id),
    FOREIGN KEY (manager_id) REFERENCES customer_manager(manager_id),
    CHECK (maturity_date >= purchase_date),
    CHECK (holding_amount <= purchase_amount)
);

CREATE TABLE channel_behavior (
    behavior_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    event_time DATETIME NOT NULL,
    channel_type TEXT NOT NULL CHECK (channel_type IN ('APP', 'WEB', 'COUNTER', 'ATM')),
    event_type TEXT NOT NULL CHECK (event_type IN ('LOGIN', 'PAGE_VIEW', 'PRODUCT_VIEW', 'TRANSACTION_ATTEMPT', 'TRANSACTION_SUCCESS')),
    session_id TEXT,
    device_type TEXT,
    event_status TEXT NOT NULL CHECK (event_status IN ('SUCCESS', 'FAILED')),
    FOREIGN KEY (customer_id) REFERENCES customer_info(customer_id),
    FOREIGN KEY (branch_id) REFERENCES branch_info(branch_id)
);

CREATE TABLE risk_event (
    risk_event_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    loan_id TEXT,
    branch_id TEXT NOT NULL,
    event_time DATETIME NOT NULL,
    risk_type TEXT NOT NULL CHECK (risk_type IN ('LOAN_OVERDUE', 'ABNORMAL_TRANSACTION', 'ACCOUNT_ANOMALY', 'FRAUD_SUSPECT')),
    risk_level TEXT NOT NULL CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH')),
    risk_score NUMERIC NOT NULL CHECK (risk_score BETWEEN 0 AND 100),
    event_status TEXT NOT NULL CHECK (event_status IN ('OPEN', 'PROCESSING', 'CLOSED', 'FALSE_POSITIVE')),
    resolved_time DATETIME,
    FOREIGN KEY (customer_id) REFERENCES customer_info(customer_id),
    FOREIGN KEY (loan_id) REFERENCES loan_info(loan_id),
    FOREIGN KEY (branch_id) REFERENCES branch_info(branch_id),
    CHECK (resolved_time IS NULL OR resolved_time >= event_time)
);

CREATE INDEX idx_manager_branch ON customer_manager(branch_id);
CREATE INDEX idx_customer_branch_level ON customer_info(branch_id, customer_level);
CREATE INDEX idx_account_customer ON account_info(customer_id);
CREATE INDEX idx_account_branch_status ON account_info(branch_id, account_status);
CREATE INDEX idx_transaction_time_branch ON transaction_detail(transaction_time, branch_id);
CREATE INDEX idx_transaction_customer ON transaction_detail(customer_id);
CREATE INDEX idx_loan_branch_status ON loan_info(branch_id, loan_status);
CREATE INDEX idx_loan_customer ON loan_info(customer_id);
CREATE INDEX idx_purchase_date_product ON product_purchase(purchase_date, product_id);
CREATE INDEX idx_purchase_customer ON product_purchase(customer_id);
CREATE INDEX idx_behavior_time_channel ON channel_behavior(event_time, channel_type);
CREATE INDEX idx_behavior_customer ON channel_behavior(customer_id);
CREATE INDEX idx_risk_time_level ON risk_event(event_time, risk_level);
CREATE INDEX idx_risk_customer ON risk_event(customer_id);
