-- Sales portal schema for MySQL 8.0 (utf8mb4). The API also creates missing tables on startup.
CREATE DATABASE IF NOT EXISTS sales_portal CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE sales_portal;

CREATE TABLE IF NOT EXISTS `grades` (
  `id` int NOT NULL AUTO_INCREMENT,
  `code` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(80) COLLATE utf8mb4_unicode_ci NOT NULL,
  `da_in` decimal(15,2) NOT NULL,
  `km_in` decimal(15,2) NOT NULL,
  `hotel_in` decimal(15,2) NOT NULL,
  `da_out` decimal(15,2) NOT NULL,
  `km_out` decimal(15,2) NOT NULL,
  `hotel_out` decimal(15,2) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
;

CREATE TABLE IF NOT EXISTS `customers` (
  `id` int NOT NULL AUTO_INCREMENT,
  `code` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(160) COLLATE utf8mb4_unicode_ci NOT NULL,
  `gstin` varchar(15) COLLATE utf8mb4_unicode_ci NOT NULL,
  `state` varchar(2) COLLATE utf8mb4_unicode_ci NOT NULL,
  `address` varchar(250) COLLATE utf8mb4_unicode_ci NOT NULL,
  `city` varchar(80) COLLATE utf8mb4_unicode_ci NOT NULL,
  `pin` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `phone` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  `email` varchar(120) COLLATE utf8mb4_unicode_ci NOT NULL,
  `price_group` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  `terms` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  `credit_limit` decimal(15,2) NOT NULL,
  `balance` decimal(15,2) NOT NULL,
  `balance_at` datetime NOT NULL,
  `blocked` tinyint(1) NOT NULL,
  `synced_at` datetime NOT NULL,
  `lat` decimal(9,6) DEFAULT NULL,
  `lng` decimal(9,6) DEFAULT NULL,
  `tagged_by` int DEFAULT NULL,
  `tagged_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_customers_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
;

CREATE TABLE IF NOT EXISTS `users` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(120) COLLATE utf8mb4_unicode_ci NOT NULL,
  `username` varchar(80) COLLATE utf8mb4_unicode_ci NOT NULL,
  `password_hash` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `role` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `emp_code` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  `phone` varchar(30) COLLATE utf8mb4_unicode_ci NOT NULL,
  `email` varchar(120) COLLATE utf8mb4_unicode_ci NOT NULL,
  `manager_id` int DEFAULT NULL,
  `territory` varchar(80) COLLATE utf8mb4_unicode_ci NOT NULL,
  `grade_code` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `active` tinyint(1) NOT NULL,
  `joined_on` date NOT NULL,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_users_username` (`username`),
  KEY `manager_id` (`manager_id`),
  CONSTRAINT `users_ibfk_1` FOREIGN KEY (`manager_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
;

CREATE TABLE IF NOT EXISTS `user_customers` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `customer_id` int NOT NULL,
  PRIMARY KEY (`id`),
  KEY `customer_id` (`customer_id`),
  KEY `ix_user_customers_user_id` (`user_id`),
  CONSTRAINT `user_customers_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `user_customers_ibfk_2` FOREIGN KEY (`customer_id`) REFERENCES `customers` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
;

CREATE TABLE IF NOT EXISTS `app_settings` (
  `key` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  `value` json NOT NULL,
  PRIMARY KEY (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
;

CREATE TABLE IF NOT EXISTS `doc_sequences` (
  `id` int NOT NULL AUTO_INCREMENT,
  `kind` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `fy` varchar(4) COLLATE utf8mb4_unicode_ci NOT NULL,
  `last` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_seq` (`kind`,`fy`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
;

CREATE TABLE IF NOT EXISTS `materials` (
  `id` int NOT NULL AUTO_INCREMENT,
  `code` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `uom` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `hsn` varchar(8) COLLATE utf8mb4_unicode_ci NOT NULL,
  `blocked` tinyint(1) NOT NULL,
  `synced_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_materials_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
;

CREATE TABLE IF NOT EXISTS `material_attributes` (
  `id` int NOT NULL AUTO_INCREMENT,
  `material_id` int NOT NULL,
  `name` varchar(60) COLLATE utf8mb4_unicode_ci NOT NULL,
  `value` varchar(120) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_mat_attr` (`material_id`,`name`),
  KEY `ix_material_attributes_material_id` (`material_id`),
  CONSTRAINT `material_attributes_ibfk_1` FOREIGN KEY (`material_id`) REFERENCES `materials` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
;

CREATE TABLE IF NOT EXISTS `prices` (
  `id` int NOT NULL AUTO_INCREMENT,
  `type` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `code` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  `material_code` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  `uom` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `price` decimal(15,2) NOT NULL,
  `min_qty` decimal(15,3) NOT NULL,
  `valid_from` date DEFAULT NULL,
  `valid_to` date DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_prices_material_code` (`material_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
;

CREATE TABLE IF NOT EXISTS `hsn_codes` (
  `code` varchar(8) COLLATE utf8mb4_unicode_ci NOT NULL,
  `description` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `rate` decimal(5,2) NOT NULL,
  `cess` decimal(5,2) NOT NULL,
  PRIMARY KEY (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
;

CREATE TABLE IF NOT EXISTS `charges` (
  `id` int NOT NULL AUTO_INCREMENT,
  `code` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(80) COLLATE utf8mb4_unicode_ci NOT NULL,
  `calc` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `value` decimal(12,3) NOT NULL,
  `sign` int NOT NULL,
  `stage` varchar(5) COLLATE utf8mb4_unicode_ci NOT NULL,
  `auto` tinyint(1) NOT NULL,
  `active` tinyint(1) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
;

CREATE TABLE IF NOT EXISTS `sales_docs` (
  `id` int NOT NULL AUTO_INCREMENT,
  `kind` varchar(5) COLLATE utf8mb4_unicode_ci NOT NULL,
  `no` varchar(30) COLLATE utf8mb4_unicode_ci NOT NULL,
  `customer_id` int NOT NULL,
  `rep_id` int NOT NULL,
  `doc_date` date NOT NULL,
  `delivery_date` date DEFAULT NULL,
  `valid_to` date DEFAULT NULL,
  `po_ref` varchar(60) COLLATE utf8mb4_unicode_ci NOT NULL,
  `remarks` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `chosen_charges` json NOT NULL,
  `totals` json NOT NULL,
  `total` decimal(15,2) NOT NULL,
  `lat` decimal(9,6) DEFAULT NULL,
  `lng` decimal(9,6) DEFAULT NULL,
  `quote_id` int DEFAULT NULL,
  `approved_by` int DEFAULT NULL,
  `approved_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  `sync_status` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `sync_no` varchar(40) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `sync_error` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `sync_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `no` (`no`),
  KEY `quote_id` (`quote_id`),
  KEY `ix_sales_docs_doc_date` (`doc_date`),
  KEY `ix_sales_docs_rep_id` (`rep_id`),
  KEY `ix_sales_docs_customer_id` (`customer_id`),
  KEY `ix_sales_docs_kind` (`kind`),
  KEY `ix_sales_docs_status` (`status`),
  CONSTRAINT `sales_docs_ibfk_1` FOREIGN KEY (`customer_id`) REFERENCES `customers` (`id`),
  CONSTRAINT `sales_docs_ibfk_2` FOREIGN KEY (`rep_id`) REFERENCES `users` (`id`),
  CONSTRAINT `sales_docs_ibfk_3` FOREIGN KEY (`quote_id`) REFERENCES `sales_docs` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
;

CREATE TABLE IF NOT EXISTS `sales_doc_lines` (
  `id` int NOT NULL AUTO_INCREMENT,
  `doc_id` int NOT NULL,
  `line_no` int NOT NULL,
  `material_code` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `uom` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `hsn` varchar(8) COLLATE utf8mb4_unicode_ci NOT NULL,
  `qty` decimal(15,3) NOT NULL,
  `price` decimal(15,2) NOT NULL,
  `disc` decimal(5,2) NOT NULL,
  `gst_rate` decimal(5,2) NOT NULL,
  `cess_rate` decimal(5,2) NOT NULL,
  `taxable` decimal(15,2) NOT NULL,
  `gst` decimal(15,2) NOT NULL,
  `price_source` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_sales_doc_lines_doc_id` (`doc_id`),
  CONSTRAINT `sales_doc_lines_ibfk_1` FOREIGN KEY (`doc_id`) REFERENCES `sales_docs` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
;

CREATE TABLE IF NOT EXISTS `payments` (
  `id` int NOT NULL AUTO_INCREMENT,
  `no` varchar(30) COLLATE utf8mb4_unicode_ci NOT NULL,
  `customer_id` int NOT NULL,
  `rep_id` int NOT NULL,
  `pay_date` date NOT NULL,
  `amount` decimal(15,2) NOT NULL,
  `mode` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `ref` varchar(60) COLLATE utf8mb4_unicode_ci NOT NULL,
  `bank` varchar(80) COLLATE utf8mb4_unicode_ci NOT NULL,
  `cheque_date` date DEFAULT NULL,
  `remarks` varchar(300) COLLATE utf8mb4_unicode_ci NOT NULL,
  `lat` decimal(9,6) DEFAULT NULL,
  `lng` decimal(9,6) DEFAULT NULL,
  `cancelled` tinyint(1) NOT NULL,
  `created_at` datetime NOT NULL,
  `sync_status` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `sync_no` varchar(40) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `sync_error` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `sync_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `no` (`no`),
  KEY `ix_payments_customer_id` (`customer_id`),
  KEY `ix_payments_pay_date` (`pay_date`),
  KEY `ix_payments_rep_id` (`rep_id`),
  CONSTRAINT `payments_ibfk_1` FOREIGN KEY (`customer_id`) REFERENCES `customers` (`id`),
  CONSTRAINT `payments_ibfk_2` FOREIGN KEY (`rep_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
;

CREATE TABLE IF NOT EXISTS `payment_allocations` (
  `id` int NOT NULL AUTO_INCREMENT,
  `payment_id` int NOT NULL,
  `order_id` int NOT NULL,
  `amount` decimal(15,2) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_payment_allocations_payment_id` (`payment_id`),
  KEY `ix_payment_allocations_order_id` (`order_id`),
  CONSTRAINT `payment_allocations_ibfk_1` FOREIGN KEY (`payment_id`) REFERENCES `payments` (`id`) ON DELETE CASCADE,
  CONSTRAINT `payment_allocations_ibfk_2` FOREIGN KEY (`order_id`) REFERENCES `sales_docs` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
;

CREATE TABLE IF NOT EXISTS `expense_claims` (
  `id` int NOT NULL AUTO_INCREMENT,
  `no` varchar(30) COLLATE utf8mb4_unicode_ci NOT NULL,
  `user_id` int NOT NULL,
  `type` varchar(3) COLLATE utf8mb4_unicode_ci NOT NULL,
  `date_from` date NOT NULL,
  `date_to` date NOT NULL,
  `purpose` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `places` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `km` decimal(10,1) NOT NULL,
  `nights` int NOT NULL,
  `hotel` decimal(15,2) NOT NULL,
  `hotel_name` varchar(120) COLLATE utf8mb4_unicode_ci NOT NULL,
  `hotel_bill` varchar(60) COLLATE utf8mb4_unicode_ci NOT NULL,
  `grade_code` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `rates` json NOT NULL,
  `calc` json NOT NULL,
  `total` decimal(15,2) NOT NULL,
  `gps_km` decimal(10,1) NOT NULL,
  `status` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `reject_reason` varchar(300) COLLATE utf8mb4_unicode_ci NOT NULL,
  `approved_by` int DEFAULT NULL,
  `approved_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `sync_status` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `sync_no` varchar(40) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `sync_error` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `sync_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `no` (`no`),
  KEY `ix_expense_claims_date_from` (`date_from`),
  KEY `ix_expense_claims_user_id` (`user_id`),
  CONSTRAINT `expense_claims_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
;

CREATE TABLE IF NOT EXISTS `expense_other` (
  `id` int NOT NULL AUTO_INCREMENT,
  `claim_id` int NOT NULL,
  `category` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  `amount` decimal(15,2) NOT NULL,
  `note` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_expense_other_claim_id` (`claim_id`),
  CONSTRAINT `expense_other_ibfk_1` FOREIGN KEY (`claim_id`) REFERENCES `expense_claims` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
;

CREATE TABLE IF NOT EXISTS `attendance` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `work_date` date NOT NULL,
  `in_at` datetime NOT NULL,
  `in_lat` decimal(9,6) DEFAULT NULL,
  `in_lng` decimal(9,6) DEFAULT NULL,
  `in_acc` int DEFAULT NULL,
  `in_addr` varchar(250) COLLATE utf8mb4_unicode_ci NOT NULL,
  `in_note` varchar(80) COLLATE utf8mb4_unicode_ci NOT NULL,
  `out_at` datetime DEFAULT NULL,
  `out_lat` decimal(9,6) DEFAULT NULL,
  `out_lng` decimal(9,6) DEFAULT NULL,
  `out_acc` int DEFAULT NULL,
  `out_addr` varchar(250) COLLATE utf8mb4_unicode_ci NOT NULL,
  `out_note` varchar(80) COLLATE utf8mb4_unicode_ci NOT NULL,
  `source` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_attendance_work_date` (`work_date`),
  KEY `ix_attendance_user_id` (`user_id`),
  CONSTRAINT `attendance_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
;

CREATE TABLE IF NOT EXISTS `attendance_corrections` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `work_date` date NOT NULL,
  `type` varchar(3) COLLATE utf8mb4_unicode_ci NOT NULL,
  `in_time` varchar(5) COLLATE utf8mb4_unicode_ci NOT NULL,
  `out_time` varchar(5) COLLATE utf8mb4_unicode_ci NOT NULL,
  `reason` varchar(300) COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `decided_by` int DEFAULT NULL,
  `decided_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_attendance_corrections_user_id` (`user_id`),
  CONSTRAINT `attendance_corrections_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
;

CREATE TABLE IF NOT EXISTS `sync_log` (
  `id` int NOT NULL AUTO_INCREMENT,
  `at` datetime NOT NULL,
  `direction` varchar(3) COLLATE utf8mb4_unicode_ci NOT NULL,
  `entity` varchar(80) COLLATE utf8mb4_unicode_ci NOT NULL,
  `count` int NOT NULL,
  `status` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `message` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `user_name` varchar(120) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_sync_log_at` (`at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
;

