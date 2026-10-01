ALTER TABLE jobs ADD COLUMN company_normalized TEXT;
CREATE INDEX IF NOT EXISTS jobs_company_normalized ON jobs(company_normalized, contract_type);
