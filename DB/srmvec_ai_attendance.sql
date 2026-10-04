-- SUPERSEDED. Do not apply this MariaDB dump.
-- Use the PostgreSQL scripts instead:
--   psql -U postgres -f DB/00_create_database.sql
--   psql -U postgres -d srm_attendance -f DB/init_postgresql.sql
--
-- phpMyAdmin SQL Dump
-- version 5.2.1
-- https://www.phpmyadmin.net/
--
-- Host: 127.0.0.1
-- Generation Time: Sep 28, 2026 at 04:27 PM
-- Server version: 10.4.32-MariaDB
-- PHP Version: 8.2.12

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

--
-- Database: `srmvec_ai_attendance`
--

DELIMITER $$
--
-- Procedures
--
CREATE DEFINER=`root`@`localhost` PROCEDURE `sp_camera_heartbeat` (IN `p_camera` BIGINT, IN `p_latency` INT)   BEGIN

INSERT INTO camera_status(

camera_id,

status,

checked_at

)

VALUES(

p_camera,

'Online',

NOW()

);

INSERT INTO camera_health_logs(

camera_id,

network_latency

)

VALUES(

p_camera,

p_latency

);

END$$

CREATE DEFINER=`root`@`localhost` PROCEDURE `sp_daily_summary` (IN `p_date` DATE)   BEGIN

DELETE FROM daily_attendance_summary

WHERE attendance_date=p_date;

INSERT INTO daily_attendance_summary(

attendance_date,

department_id,

section_id,

total_students,

present_count,

absent_count,

attendance_percentage

)

SELECT

p_date,

d.id,

sec.id,

COUNT(DISTINCT s.id),

SUM(a.status='Present'),

SUM(a.status='Absent'),

ROUND(

SUM(a.status='Present')*100/

COUNT(a.id),

2

)

FROM departments d

JOIN sections sec
ON sec.department_id=d.id

JOIN students s
ON s.section_id=sec.id

LEFT JOIN attendance a
ON a.student_id=s.id

AND a.attendance_date=p_date

GROUP BY d.id,sec.id;

END$$

CREATE DEFINER=`root`@`localhost` PROCEDURE `sp_generate_defaulters` ()   BEGIN

DELETE FROM attendance_alerts;

INSERT INTO attendance_alerts(

student_id,

subject_id,

percentage,

alert_type

)

SELECT

student_id,

subject_id,

percentage,

CASE

WHEN percentage<50 THEN 'Critical'

WHEN percentage<60 THEN 'Below60'

ELSE 'Below75'

END

FROM attendance_summary

WHERE percentage<75;

END$$

CREATE DEFINER=`root`@`localhost` PROCEDURE `sp_log_export` (IN `p_user` BIGINT, IN `p_name` VARCHAR(200), IN `p_type` VARCHAR(20), IN `p_path` VARCHAR(255))   BEGIN

INSERT INTO report_exports(

exported_by,

report_name,

report_type,

file_path

)

VALUES(

p_user,

p_name,

p_type,

p_path

);

END$$

CREATE DEFINER=`root`@`localhost` PROCEDURE `sp_process_ai_detection` (IN `p_student` BIGINT, IN `p_camera` BIGINT, IN `p_time` DATETIME, IN `p_conf` DECIMAL(5,2))   BEGIN

INSERT INTO recognition_logs(

camera_id,

student_id,

detection_time,

confidence,

recognition_status,

attendance_processed

)

VALUES(

p_camera,

p_student,

p_time,

p_conf,

'Recognized',

FALSE

);

END$$

CREATE DEFINER=`root`@`localhost` PROCEDURE `sp_recalculate_summary` ()   BEGIN

DELETE FROM attendance_summary;

INSERT INTO attendance_summary(

student_id,

subject_id,

academic_year_id,

semester_id,

total_classes,

attended_classes,

absent_classes,

percentage

)

SELECT

a.student_id,

t.subject_id,

t.academic_year_id,

t.semester_id,

COUNT(*),

SUM(a.status='Present'),

SUM(a.status='Absent'),

ROUND(

SUM(a.status='Present')*100/

COUNT(*),

2

)

FROM attendance a

JOIN timetable t
ON a.timetable_id=t.id

GROUP BY

a.student_id,

t.subject_id,

t.semester_id;

END$$

CREATE DEFINER=`root`@`localhost` PROCEDURE `sp_unknown_face` (IN `p_camera` BIGINT, IN `p_image` VARCHAR(255), IN `p_conf` DECIMAL(5,2))   BEGIN

INSERT INTO unknown_faces(

camera_id,

image_path,

confidence,

first_seen,

last_seen

)

VALUES(

p_camera,

p_image,

p_conf,

NOW(),

NOW()

);

END$$

DELIMITER ;

-- --------------------------------------------------------

--
-- Table structure for table `academic_years`
--

CREATE TABLE `academic_years` (
  `id` int(11) NOT NULL,
  `academic_year` varchar(20) DEFAULT NULL,
  `start_date` date DEFAULT NULL,
  `end_date` date DEFAULT NULL,
  `is_active` tinyint(1) DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `academic_years`
--

INSERT INTO `academic_years` (`id`, `academic_year`, `start_date`, `end_date`, `is_active`) VALUES
(1, '2026-2027', '2026-07-01', '2027-06-30', 1);

-- --------------------------------------------------------

--
-- Table structure for table `ai_model_settings`
--

CREATE TABLE `ai_model_settings` (
  `id` int(11) NOT NULL,
  `model_name` varchar(100) DEFAULT NULL,
  `confidence_threshold` decimal(5,2) DEFAULT NULL,
  `attendance_threshold_minutes` int(11) DEFAULT NULL,
  `is_active` tinyint(1) DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `ai_model_settings`
--

INSERT INTO `ai_model_settings` (`id`, `model_name`, `confidence_threshold`, `attendance_threshold_minutes`, `is_active`) VALUES
(1, 'InsightFace ArcFace', 0.70, 45, 1);

-- --------------------------------------------------------

--
-- Table structure for table `ai_tracking_sessions`
--

CREATE TABLE `ai_tracking_sessions` (
  `id` bigint(20) NOT NULL,
  `camera_id` bigint(20) DEFAULT NULL,
  `tracking_id` varchar(100) DEFAULT NULL,
  `student_id` bigint(20) DEFAULT NULL,
  `first_detected` datetime DEFAULT NULL,
  `last_detected` datetime DEFAULT NULL,
  `total_duration_seconds` int(11) DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `attendance`
--

CREATE TABLE `attendance` (
  `id` bigint(20) NOT NULL,
  `student_id` bigint(20) DEFAULT NULL,
  `timetable_id` bigint(20) DEFAULT NULL,
  `attendance_date` date DEFAULT NULL,
  `entry_time` datetime DEFAULT NULL,
  `exit_time` datetime DEFAULT NULL,
  `duration_minutes` int(11) DEFAULT 0,
  `attendance_source` enum('AI','Manual','Imported') DEFAULT 'AI',
  `confidence` decimal(5,2) DEFAULT NULL,
  `status` enum('Present','Absent','Late','Excused') DEFAULT NULL,
  `marked_by` bigint(20) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Triggers `attendance`
--
DELIMITER $$
CREATE TRIGGER `trg_attendance_duration` BEFORE INSERT ON `attendance` FOR EACH ROW BEGIN

    IF NEW.duration_minutes >= 45 THEN
        SET NEW.status='Present';

    ELSEIF NEW.duration_minutes>0 THEN
        SET NEW.status='Absent';
    END IF;

END
$$
DELIMITER ;
DELIMITER $$
CREATE TRIGGER `trg_attendance_update` AFTER UPDATE ON `attendance` FOR EACH ROW BEGIN

IF OLD.status<>NEW.status THEN

INSERT INTO student_attendance_history(

student_id,

attendance_date,

timetable_id,

previous_status,

new_status,

modified_by

)

VALUES(

NEW.student_id,

NEW.attendance_date,

NEW.timetable_id,

OLD.status,

NEW.status,

NEW.marked_by

);

END IF;

END
$$
DELIMITER ;
DELIMITER $$
CREATE TRIGGER `trg_duplicate_attendance` BEFORE INSERT ON `attendance` FOR EACH ROW BEGIN

IF EXISTS(

SELECT 1

FROM attendance

WHERE student_id=NEW.student_id

AND timetable_id=NEW.timetable_id

AND attendance_date=NEW.attendance_date

)

THEN

SIGNAL SQLSTATE '45000'

SET MESSAGE_TEXT='Attendance already exists';

END IF;

END
$$
DELIMITER ;

-- --------------------------------------------------------

--
-- Table structure for table `attendance_alerts`
--

CREATE TABLE `attendance_alerts` (
  `id` bigint(20) NOT NULL,
  `student_id` bigint(20) DEFAULT NULL,
  `subject_id` bigint(20) DEFAULT NULL,
  `percentage` decimal(5,2) DEFAULT NULL,
  `alert_type` enum('Below75','Below60','Critical') DEFAULT NULL,
  `generated_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `attendance_corrections`
--

CREATE TABLE `attendance_corrections` (
  `id` bigint(20) NOT NULL,
  `attendance_id` bigint(20) DEFAULT NULL,
  `old_status` varchar(20) DEFAULT NULL,
  `new_status` varchar(20) DEFAULT NULL,
  `reason` text DEFAULT NULL,
  `corrected_by` bigint(20) DEFAULT NULL,
  `corrected_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `attendance_logs`
--

CREATE TABLE `attendance_logs` (
  `id` bigint(20) NOT NULL,
  `attendance_id` bigint(20) DEFAULT NULL,
  `student_id` bigint(20) DEFAULT NULL,
  `camera_id` bigint(20) DEFAULT NULL,
  `detection_time` datetime DEFAULT NULL,
  `confidence` decimal(5,2) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `attendance_summary`
--

CREATE TABLE `attendance_summary` (
  `id` bigint(20) NOT NULL,
  `student_id` bigint(20) DEFAULT NULL,
  `subject_id` bigint(20) DEFAULT NULL,
  `academic_year_id` int(11) DEFAULT NULL,
  `semester_id` int(11) DEFAULT NULL,
  `total_classes` int(11) DEFAULT 0,
  `attended_classes` int(11) DEFAULT 0,
  `absent_classes` int(11) DEFAULT 0,
  `percentage` decimal(5,2) DEFAULT NULL,
  `last_updated` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `audit_logs`
--

CREATE TABLE `audit_logs` (
  `id` bigint(20) NOT NULL,
  `user_id` bigint(20) DEFAULT NULL,
  `action` varchar(255) DEFAULT NULL,
  `table_name` varchar(100) DEFAULT NULL,
  `record_id` bigint(20) DEFAULT NULL,
  `action_time` timestamp NOT NULL DEFAULT current_timestamp(),
  `ip_address` varchar(50) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `backup_logs`
--

CREATE TABLE `backup_logs` (
  `id` bigint(20) NOT NULL,
  `backup_name` varchar(255) DEFAULT NULL,
  `backup_type` enum('Full','Incremental') DEFAULT NULL,
  `backup_location` varchar(255) DEFAULT NULL,
  `backup_size_mb` decimal(10,2) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `cameras`
--

CREATE TABLE `cameras` (
  `id` bigint(20) NOT NULL,
  `camera_name` varchar(150) DEFAULT NULL,
  `vendor_id` int(11) DEFAULT NULL,
  `classroom_id` int(11) DEFAULT NULL,
  `ip_address` varchar(50) DEFAULT NULL,
  `rtsp_url` text DEFAULT NULL,
  `username` varchar(100) DEFAULT NULL,
  `password` varchar(255) DEFAULT NULL,
  `resolution` varchar(50) DEFAULT NULL,
  `fps` int(11) DEFAULT NULL,
  `status` enum('Online','Offline','Maintenance') DEFAULT 'Offline',
  `installed_on` date DEFAULT NULL,
  `remarks` text DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `cameras`
--

INSERT INTO `cameras` (`id`, `camera_name`, `vendor_id`, `classroom_id`, `ip_address`, `rtsp_url`, `username`, `password`, `resolution`, `fps`, `status`, `installed_on`, `remarks`, `created_at`) VALUES
(1, 'CSE-510-Front', 1, 3, '192.168.1.101', 'rtsp://admin:password@192.168.1.101:554/Streaming/Channels/101', NULL, NULL, '1920x1080', 25, 'Online', NULL, NULL, '2026-09-28 14:22:50');

-- --------------------------------------------------------

--
-- Table structure for table `camera_assignments`
--

CREATE TABLE `camera_assignments` (
  `id` bigint(20) NOT NULL,
  `camera_id` bigint(20) DEFAULT NULL,
  `classroom_id` int(11) DEFAULT NULL,
  `angle` enum('Front','Back','Left','Right','Ceiling') DEFAULT NULL,
  `is_active` tinyint(1) DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `camera_event_logs`
--

CREATE TABLE `camera_event_logs` (
  `id` bigint(20) NOT NULL,
  `camera_id` bigint(20) DEFAULT NULL,
  `event_type` enum('Started','Stopped','Disconnected','Reconnected','Recording') DEFAULT NULL,
  `event_time` datetime DEFAULT NULL,
  `description` text DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `camera_health_logs`
--

CREATE TABLE `camera_health_logs` (
  `id` bigint(20) NOT NULL,
  `camera_id` bigint(20) DEFAULT NULL,
  `cpu_usage` decimal(5,2) DEFAULT NULL,
  `memory_usage` decimal(5,2) DEFAULT NULL,
  `temperature` decimal(5,2) DEFAULT NULL,
  `network_latency` int(11) DEFAULT NULL,
  `recorded_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `camera_status`
--

CREATE TABLE `camera_status` (
  `id` bigint(20) NOT NULL,
  `camera_id` bigint(20) DEFAULT NULL,
  `status` enum('Online','Offline') DEFAULT NULL,
  `checked_at` datetime DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `camera_vendors`
--

CREATE TABLE `camera_vendors` (
  `id` int(11) NOT NULL,
  `vendor_name` varchar(100) DEFAULT NULL,
  `rtsp_format` text DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `camera_vendors`
--

INSERT INTO `camera_vendors` (`id`, `vendor_name`, `rtsp_format`) VALUES
(1, 'CP Plus', 'rtsp://user:password@ip:554/Streaming/Channels/101'),
(2, 'Hikvision', 'rtsp://user:password@ip:554/Streaming/Channels/101'),
(3, 'Dahua', 'rtsp://user:password@ip:554/cam/realmonitor?channel=1&subtype=0');

-- --------------------------------------------------------

--
-- Table structure for table `classrooms`
--

CREATE TABLE `classrooms` (
  `id` int(11) NOT NULL,
  `room_number` varchar(20) DEFAULT NULL,
  `block_name` varchar(50) DEFAULT NULL,
  `floor_no` int(11) DEFAULT NULL,
  `capacity` int(11) DEFAULT NULL,
  `has_cctv` tinyint(1) DEFAULT 1,
  `remarks` varchar(255) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `classrooms`
--

INSERT INTO `classrooms` (`id`, `room_number`, `block_name`, `floor_no`, `capacity`, `has_cctv`, `remarks`) VALUES
(1, '508', 'CSE Block', 5, 70, 1, NULL),
(2, '509', 'CSE Block', 5, 70, 1, NULL),
(3, '510', 'CSE Block', 5, 70, 1, NULL);

-- --------------------------------------------------------

--
-- Table structure for table `class_swaps`
--

CREATE TABLE `class_swaps` (
  `id` bigint(20) NOT NULL,
  `original_staff` bigint(20) DEFAULT NULL,
  `replacement_staff` bigint(20) DEFAULT NULL,
  `timetable_id` bigint(20) DEFAULT NULL,
  `swap_date` date DEFAULT NULL,
  `approved_by` bigint(20) DEFAULT NULL,
  `status` enum('Pending','Approved','Rejected') DEFAULT 'Pending'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `daily_attendance_summary`
--

CREATE TABLE `daily_attendance_summary` (
  `id` bigint(20) NOT NULL,
  `attendance_date` date DEFAULT NULL,
  `department_id` int(11) DEFAULT NULL,
  `section_id` int(11) DEFAULT NULL,
  `total_students` int(11) DEFAULT 0,
  `present_count` int(11) DEFAULT 0,
  `absent_count` int(11) DEFAULT 0,
  `attendance_percentage` decimal(5,2) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `departments`
--

CREATE TABLE `departments` (
  `id` int(11) NOT NULL,
  `department_code` varchar(20) DEFAULT NULL,
  `department_name` varchar(150) DEFAULT NULL,
  `hod_id` bigint(20) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `departments`
--

INSERT INTO `departments` (`id`, `department_code`, `department_name`, `hod_id`, `created_at`) VALUES
(1, 'CSE', 'Computer Science and Engineering', NULL, '2026-09-28 14:19:42'),
(2, 'MCA', 'Master of Computer Applications', NULL, '2026-09-28 14:19:42'),
(3, 'IT', 'Information Technology', NULL, '2026-09-28 14:19:42'),
(4, 'ECE', 'Electronics and Communication Engineering', NULL, '2026-09-28 14:19:42'),
(5, 'EEE', 'Electrical and Electronics Engineering', NULL, '2026-09-28 14:19:42'),
(6, 'MECH', 'Mechanical Engineering', NULL, '2026-09-28 14:19:42');

-- --------------------------------------------------------

--
-- Table structure for table `email_queue`
--

CREATE TABLE `email_queue` (
  `id` bigint(20) NOT NULL,
  `student_id` bigint(20) DEFAULT NULL,
  `email` varchar(150) DEFAULT NULL,
  `subject` varchar(255) DEFAULT NULL,
  `message` text DEFAULT NULL,
  `status` enum('Pending','Sent','Failed') DEFAULT 'Pending',
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `sent_at` datetime DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `face_embeddings`
--

CREATE TABLE `face_embeddings` (
  `id` bigint(20) NOT NULL,
  `student_id` bigint(20) DEFAULT NULL,
  `embedding` longblob DEFAULT NULL,
  `model_name` varchar(100) DEFAULT NULL,
  `embedding_version` int(11) DEFAULT 1,
  `generated_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Triggers `face_embeddings`
--
DELIMITER $$
CREATE TRIGGER `trg_face_registered` AFTER INSERT ON `face_embeddings` FOR EACH ROW BEGIN

UPDATE students

SET face_registered=TRUE

WHERE id=NEW.student_id;

END
$$
DELIMITER ;

-- --------------------------------------------------------

--
-- Table structure for table `face_registration_images`
--

CREATE TABLE `face_registration_images` (
  `id` bigint(20) NOT NULL,
  `session_id` bigint(20) DEFAULT NULL,
  `student_id` bigint(20) DEFAULT NULL,
  `angle` enum('Front','Left','Right','Up','Down') DEFAULT NULL,
  `image_path` varchar(255) DEFAULT NULL,
  `embedding_generated` tinyint(1) DEFAULT 0,
  `uploaded_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `face_registration_sessions`
--

CREATE TABLE `face_registration_sessions` (
  `id` bigint(20) NOT NULL,
  `student_id` bigint(20) DEFAULT NULL,
  `registered_by` bigint(20) DEFAULT NULL,
  `registered_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `holidays`
--

CREATE TABLE `holidays` (
  `id` bigint(20) NOT NULL,
  `academic_year_id` int(11) DEFAULT NULL,
  `holiday_name` varchar(200) DEFAULT NULL,
  `holiday_date` date DEFAULT NULL,
  `holiday_type` enum('Government','College','Exam','Festival') DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `monthly_attendance_summary`
--

CREATE TABLE `monthly_attendance_summary` (
  `id` bigint(20) NOT NULL,
  `academic_year_id` int(11) DEFAULT NULL,
  `month_no` int(11) DEFAULT NULL,
  `department_id` int(11) DEFAULT NULL,
  `section_id` int(11) DEFAULT NULL,
  `total_classes` int(11) DEFAULT NULL,
  `total_present` int(11) DEFAULT NULL,
  `total_absent` int(11) DEFAULT NULL,
  `attendance_percentage` decimal(5,2) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `notifications`
--

CREATE TABLE `notifications` (
  `id` bigint(20) NOT NULL,
  `user_id` bigint(20) DEFAULT NULL,
  `title` varchar(200) DEFAULT NULL,
  `message` text DEFAULT NULL,
  `notification_type` enum('Attendance','Leave','Announcement','System') DEFAULT NULL,
  `is_read` tinyint(1) DEFAULT 0,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `periods`
--

CREATE TABLE `periods` (
  `id` int(11) NOT NULL,
  `period_no` int(11) DEFAULT NULL,
  `start_time` time DEFAULT NULL,
  `end_time` time DEFAULT NULL,
  `duration_minutes` int(11) DEFAULT 50
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `periods`
--

INSERT INTO `periods` (`id`, `period_no`, `start_time`, `end_time`, `duration_minutes`) VALUES
(1, 1, '08:15:00', '09:05:00', 50),
(2, 2, '09:05:00', '09:55:00', 50),
(3, 3, '10:10:00', '11:00:00', 50),
(4, 4, '11:00:00', '11:50:00', 50),
(5, 5, '12:30:00', '13:20:00', 50),
(6, 6, '13:20:00', '14:10:00', 50),
(7, 7, '14:20:00', '15:10:00', 50);

-- --------------------------------------------------------

--
-- Table structure for table `programs`
--

CREATE TABLE `programs` (
  `id` int(11) NOT NULL,
  `program_code` varchar(20) DEFAULT NULL,
  `program_name` varchar(150) DEFAULT NULL,
  `duration_years` int(11) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `programs`
--

INSERT INTO `programs` (`id`, `program_code`, `program_name`, `duration_years`, `created_at`) VALUES
(1, 'BE-CSE', 'B.E Computer Science and Engineering', 4, '2026-09-28 14:19:42'),
(2, 'MCA', 'Master of Computer Applications', 2, '2026-09-28 14:19:42');

-- --------------------------------------------------------

--
-- Table structure for table `recognition_logs`
--

CREATE TABLE `recognition_logs` (
  `id` bigint(20) NOT NULL,
  `camera_id` bigint(20) DEFAULT NULL,
  `student_id` bigint(20) DEFAULT NULL,
  `detection_time` datetime DEFAULT NULL,
  `confidence` decimal(5,2) DEFAULT NULL,
  `bounding_box` varchar(255) DEFAULT NULL,
  `recognition_status` enum('Recognized','Unknown') DEFAULT NULL,
  `attendance_processed` tinyint(1) DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `report_exports`
--

CREATE TABLE `report_exports` (
  `id` bigint(20) NOT NULL,
  `exported_by` bigint(20) DEFAULT NULL,
  `report_name` varchar(200) DEFAULT NULL,
  `report_type` enum('Excel','PDF') DEFAULT NULL,
  `file_path` varchar(255) DEFAULT NULL,
  `exported_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `roles`
--

CREATE TABLE `roles` (
  `id` int(11) NOT NULL,
  `role_name` varchar(50) NOT NULL,
  `description` varchar(255) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `roles`
--

INSERT INTO `roles` (`id`, `role_name`, `description`, `created_at`) VALUES
(1, 'Super Admin', 'Complete ERP control', '2026-09-28 14:19:42'),
(2, 'Admin', 'Department administration', '2026-09-28 14:19:42'),
(3, 'HOD', 'Department monitoring', '2026-09-28 14:19:42'),
(4, 'Class Advisor', 'Class management', '2026-09-28 14:19:42'),
(5, 'Staff', 'Faculty access', '2026-09-28 14:19:42'),
(6, 'Student', 'Student portal', '2026-09-28 14:19:42');

-- --------------------------------------------------------

--
-- Table structure for table `sections`
--

CREATE TABLE `sections` (
  `id` int(11) NOT NULL,
  `department_id` int(11) DEFAULT NULL,
  `program_id` int(11) DEFAULT NULL,
  `academic_year_id` int(11) DEFAULT NULL,
  `semester_id` int(11) DEFAULT NULL,
  `section_name` varchar(20) DEFAULT NULL,
  `strength` int(11) DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `sections`
--

INSERT INTO `sections` (`id`, `department_id`, `program_id`, `academic_year_id`, `semester_id`, `section_name`, `strength`) VALUES
(1, 1, 1, 1, NULL, 'II Year A', 70),
(2, 1, 1, 1, NULL, 'II Year B', 70),
(3, 2, 2, 1, NULL, 'MCA II', 120),
(4, 1, 1, 1, 3, 'II Year A', 70),
(5, 1, 1, 1, 3, 'II Year B', 70),
(6, 2, 2, 1, 1, 'MCA II', 120);

-- --------------------------------------------------------

--
-- Table structure for table `semesters`
--

CREATE TABLE `semesters` (
  `id` int(11) NOT NULL,
  `academic_year_id` int(11) DEFAULT NULL,
  `semester_no` int(11) DEFAULT NULL,
  `start_date` date DEFAULT NULL,
  `end_date` date DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `semesters`
--

INSERT INTO `semesters` (`id`, `academic_year_id`, `semester_no`, `start_date`, `end_date`) VALUES
(1, 1, 1, '2026-07-01', '2026-11-30'),
(2, 1, 2, '2026-12-01', '2027-04-30'),
(3, 1, 3, '2027-07-01', '2027-11-30'),
(4, 1, 4, '2027-12-01', '2028-04-30');

-- --------------------------------------------------------

--
-- Table structure for table `sms_queue`
--

CREATE TABLE `sms_queue` (
  `id` bigint(20) NOT NULL,
  `student_id` bigint(20) DEFAULT NULL,
  `mobile_number` varchar(20) DEFAULT NULL,
  `message` text DEFAULT NULL,
  `status` enum('Pending','Sent','Failed') DEFAULT 'Pending',
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `sent_at` datetime DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `staff`
--

CREATE TABLE `staff` (
  `id` bigint(20) NOT NULL,
  `user_id` bigint(20) NOT NULL,
  `staff_code` varchar(30) NOT NULL,
  `designation` varchar(100) DEFAULT NULL,
  `qualification` varchar(150) DEFAULT NULL,
  `experience_years` decimal(4,1) DEFAULT NULL,
  `joining_date` date DEFAULT NULL,
  `department_id` int(11) NOT NULL,
  `employee_type` enum('Regular','Contract','Visiting') DEFAULT 'Regular',
  `status` enum('Active','Medical Leave','Relieved') DEFAULT 'Active',
  `created_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `staff`
--

INSERT INTO `staff` (`id`, `user_id`, `staff_code`, `designation`, `qualification`, `experience_years`, `joining_date`, `department_id`, `employee_type`, `status`, `created_at`) VALUES
(1, 1, 'SA001', 'System Administrator', NULL, 10.0, NULL, 1, 'Regular', 'Active', '2026-09-28 14:22:50'),
(2, 2, 'HOD001', 'Professor & HOD', NULL, 18.0, NULL, 1, 'Regular', 'Active', '2026-09-28 14:22:50');

-- --------------------------------------------------------

--
-- Table structure for table `staff_sections`
--

CREATE TABLE `staff_sections` (
  `id` bigint(20) NOT NULL,
  `staff_id` bigint(20) DEFAULT NULL,
  `section_id` int(11) DEFAULT NULL,
  `role` enum('Subject Staff','Class Advisor','Mentor') DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `staff_subjects`
--

CREATE TABLE `staff_subjects` (
  `id` bigint(20) NOT NULL,
  `staff_id` bigint(20) DEFAULT NULL,
  `subject_id` bigint(20) DEFAULT NULL,
  `academic_year_id` int(11) DEFAULT NULL,
  `semester_id` int(11) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `students`
--

CREATE TABLE `students` (
  `id` bigint(20) NOT NULL,
  `user_id` bigint(20) DEFAULT NULL,
  `register_no` varchar(30) DEFAULT NULL,
  `admission_no` varchar(30) DEFAULT NULL,
  `roll_no` varchar(20) DEFAULT NULL,
  `section_id` int(11) DEFAULT NULL,
  `batch_year` year(4) DEFAULT NULL,
  `gender` enum('Male','Female','Other') DEFAULT NULL,
  `dob` date DEFAULT NULL,
  `blood_group` varchar(10) DEFAULT NULL,
  `address` text DEFAULT NULL,
  `profile_photo` varchar(255) DEFAULT NULL,
  `face_registered` tinyint(1) DEFAULT 0,
  `status` enum('Active','Alumni','Discontinued') DEFAULT 'Active',
  `created_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `students`
--

INSERT INTO `students` (`id`, `user_id`, `register_no`, `admission_no`, `roll_no`, `section_id`, `batch_year`, `gender`, `dob`, `blood_group`, `address`, `profile_photo`, `face_registered`, `status`, `created_at`) VALUES
(1, 3, '22CS001', NULL, NULL, 1, '2022', NULL, NULL, NULL, NULL, NULL, 0, 'Active', '2026-09-28 14:22:50'),
(2, 4, '22CS002', NULL, NULL, 1, '2022', NULL, NULL, NULL, NULL, NULL, 0, 'Active', '2026-09-28 14:22:50'),
(3, 5, '22MC001', NULL, NULL, 3, '2025', NULL, NULL, NULL, NULL, NULL, 0, 'Active', '2026-09-28 14:22:50');

-- --------------------------------------------------------

--
-- Table structure for table `student_attendance_history`
--

CREATE TABLE `student_attendance_history` (
  `id` bigint(20) NOT NULL,
  `student_id` bigint(20) DEFAULT NULL,
  `attendance_date` date DEFAULT NULL,
  `timetable_id` bigint(20) DEFAULT NULL,
  `previous_status` varchar(20) DEFAULT NULL,
  `new_status` varchar(20) DEFAULT NULL,
  `modified_by` bigint(20) DEFAULT NULL,
  `modified_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `student_devices`
--

CREATE TABLE `student_devices` (
  `id` bigint(20) NOT NULL,
  `student_id` bigint(20) DEFAULT NULL,
  `device_id` varchar(255) DEFAULT NULL,
  `device_name` varchar(150) DEFAULT NULL,
  `firebase_token` text DEFAULT NULL,
  `last_sync` datetime DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `student_parents`
--

CREATE TABLE `student_parents` (
  `id` bigint(20) NOT NULL,
  `student_id` bigint(20) DEFAULT NULL,
  `father_name` varchar(150) DEFAULT NULL,
  `mother_name` varchar(150) DEFAULT NULL,
  `guardian_name` varchar(150) DEFAULT NULL,
  `father_mobile` varchar(20) DEFAULT NULL,
  `mother_mobile` varchar(20) DEFAULT NULL,
  `guardian_mobile` varchar(20) DEFAULT NULL,
  `email` varchar(150) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `student_photo_history`
--

CREATE TABLE `student_photo_history` (
  `id` bigint(20) NOT NULL,
  `student_id` bigint(20) DEFAULT NULL,
  `photo_path` varchar(255) DEFAULT NULL,
  `uploaded_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `subjects`
--

CREATE TABLE `subjects` (
  `id` bigint(20) NOT NULL,
  `subject_code` varchar(30) DEFAULT NULL,
  `subject_name` varchar(200) DEFAULT NULL,
  `category_id` int(11) DEFAULT NULL,
  `department_id` int(11) DEFAULT NULL,
  `semester_no` int(11) DEFAULT NULL,
  `credits` decimal(3,1) DEFAULT NULL,
  `total_hours` int(11) DEFAULT NULL,
  `is_lab` tinyint(1) DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `subjects`
--

INSERT INTO `subjects` (`id`, `subject_code`, `subject_name`, `category_id`, `department_id`, `semester_no`, `credits`, `total_hours`, `is_lab`) VALUES
(1, 'CS201', 'Data Structures', 1, 1, 3, 4.0, 60, 0),
(2, 'CS301', 'Database Management Systems', 1, 1, 4, 4.0, 60, 0),
(3, 'MC4261', 'Data Visualization', 1, 2, 2, 4.0, 60, 0),
(4, 'MC4268', 'Mini Project', 4, 2, 2, 2.0, 30, 1);

-- --------------------------------------------------------

--
-- Table structure for table `subject_categories`
--

CREATE TABLE `subject_categories` (
  `id` int(11) NOT NULL,
  `category_name` varchar(100) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `subject_categories`
--

INSERT INTO `subject_categories` (`id`, `category_name`) VALUES
(1, 'Core'),
(2, 'Professional Elective'),
(3, 'Open Elective'),
(4, 'Lab'),
(5, 'Audit Course');

-- --------------------------------------------------------

--
-- Table structure for table `system_maintenance`
--

CREATE TABLE `system_maintenance` (
  `id` bigint(20) NOT NULL,
  `maintenance_type` varchar(150) DEFAULT NULL,
  `description` text DEFAULT NULL,
  `performed_by` bigint(20) DEFAULT NULL,
  `performed_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `system_settings`
--

CREATE TABLE `system_settings` (
  `id` int(11) NOT NULL,
  `setting_key` varchar(100) DEFAULT NULL,
  `setting_value` text DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `system_settings`
--

INSERT INTO `system_settings` (`id`, `setting_key`, `setting_value`) VALUES
(1, 'college_name', 'SRM Valliammai Engineering College'),
(2, 'attendance_threshold', '75'),
(3, 'attendance_rule_minutes', '45'),
(4, 'period_duration', '50');

-- --------------------------------------------------------

--
-- Table structure for table `timetable`
--

CREATE TABLE `timetable` (
  `id` bigint(20) NOT NULL,
  `academic_year_id` int(11) NOT NULL,
  `semester_id` int(11) NOT NULL,
  `section_id` int(11) NOT NULL,
  `subject_id` bigint(20) NOT NULL,
  `staff_id` bigint(20) NOT NULL,
  `classroom_id` int(11) NOT NULL,
  `day_of_week` enum('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday') DEFAULT NULL,
  `period_id` int(11) NOT NULL,
  `is_active` tinyint(1) DEFAULT 1,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `timetable`
--

INSERT INTO `timetable` (`id`, `academic_year_id`, `semester_id`, `section_id`, `subject_id`, `staff_id`, `classroom_id`, `day_of_week`, `period_id`, `is_active`, `created_at`) VALUES
(1, 1, 3, 1, 1, 1, 3, 'Monday', 1, 1, '2026-09-28 14:24:10');

-- --------------------------------------------------------

--
-- Table structure for table `timetable_history`
--

CREATE TABLE `timetable_history` (
  `id` bigint(20) NOT NULL,
  `timetable_id` bigint(20) DEFAULT NULL,
  `modified_by` bigint(20) DEFAULT NULL,
  `old_staff` bigint(20) DEFAULT NULL,
  `new_staff` bigint(20) DEFAULT NULL,
  `modified_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `unknown_faces`
--

CREATE TABLE `unknown_faces` (
  `id` bigint(20) NOT NULL,
  `camera_id` bigint(20) DEFAULT NULL,
  `image_path` varchar(255) DEFAULT NULL,
  `confidence` decimal(5,2) DEFAULT NULL,
  `first_seen` datetime DEFAULT NULL,
  `last_seen` datetime DEFAULT NULL,
  `occurrence_count` int(11) DEFAULT 1,
  `reviewed` tinyint(1) DEFAULT 0,
  `reviewed_by` bigint(20) DEFAULT NULL,
  `remarks` text DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `users`
--

CREATE TABLE `users` (
  `id` bigint(20) NOT NULL,
  `username` varchar(100) NOT NULL,
  `password_hash` varchar(255) NOT NULL,
  `role_id` int(11) NOT NULL,
  `department_id` int(11) DEFAULT NULL,
  `first_name` varchar(100) DEFAULT NULL,
  `last_name` varchar(100) DEFAULT NULL,
  `email` varchar(150) DEFAULT NULL,
  `mobile` varchar(20) DEFAULT NULL,
  `profile_photo` varchar(255) DEFAULT NULL,
  `status` enum('Active','Inactive') DEFAULT 'Active',
  `last_login` datetime DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `users`
--

INSERT INTO `users` (`id`, `username`, `password_hash`, `role_id`, `department_id`, `first_name`, `last_name`, `email`, `mobile`, `profile_photo`, `status`, `last_login`, `created_at`) VALUES
(1, 'superadmin', '$2b$10$abcdefghijklmnopqrstuv', 1, 1, 'System', NULL, 'superadmin@srmvec.edu', NULL, NULL, 'Active', NULL, '2026-09-28 14:22:50'),
(2, 'hod_cse', '$2b$10$abcdefghijklmnopqrstuv', 3, 1, 'Head', NULL, 'hodcse@srmvec.edu', NULL, NULL, 'Active', NULL, '2026-09-28 14:22:50'),
(3, '22CS001', '$2b$10$abcdefghijklmnopqrstuv', 6, 1, 'Student1', NULL, NULL, NULL, NULL, 'Active', NULL, '2026-09-28 14:22:50'),
(4, '22CS002', '$2b$10$abcdefghijklmnopqrstuv', 6, 1, 'Student2', NULL, NULL, NULL, NULL, 'Active', NULL, '2026-09-28 14:22:50'),
(5, '22MC001', '$2b$10$abcdefghijklmnopqrstuv', 6, 2, 'MCAStudent', NULL, NULL, NULL, NULL, 'Active', NULL, '2026-09-28 14:22:50');

-- --------------------------------------------------------

--
-- Table structure for table `user_sessions`
--

CREATE TABLE `user_sessions` (
  `id` bigint(20) NOT NULL,
  `user_id` bigint(20) DEFAULT NULL,
  `session_token` varchar(255) DEFAULT NULL,
  `login_time` datetime DEFAULT NULL,
  `logout_time` datetime DEFAULT NULL,
  `ip_address` varchar(50) DEFAULT NULL,
  `device` varchar(255) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Stand-in structure for view `vw_ai_summary`
-- (See below for the actual view)
--
CREATE TABLE `vw_ai_summary` (
`detection_date` date
,`total_detections` bigint(21)
,`recognized` decimal(23,0)
,`unknown_faces` decimal(23,0)
);

-- --------------------------------------------------------

--
-- Stand-in structure for view `vw_camera_dashboard`
-- (See below for the actual view)
--
CREATE TABLE `vw_camera_dashboard` (
`id` bigint(20)
,`camera_name` varchar(150)
,`room_number` varchar(20)
,`status` enum('Online','Offline','Maintenance')
,`ip_address` varchar(50)
,`resolution` varchar(50)
,`fps` int(11)
);

-- --------------------------------------------------------

--
-- Stand-in structure for view `vw_class_advisor_dashboard`
-- (See below for the actual view)
--
CREATE TABLE `vw_class_advisor_dashboard` (
`section_name` varchar(20)
,`total_students` bigint(21)
,`attendance_percentage` decimal(29,2)
);

-- --------------------------------------------------------

--
-- Stand-in structure for view `vw_daily_report`
-- (See below for the actual view)
--
CREATE TABLE `vw_daily_report` (
`attendance_date` date
,`subject_name` varchar(200)
,`section_name` varchar(20)
,`present` decimal(23,0)
,`absent` decimal(23,0)
);

-- --------------------------------------------------------

--
-- Stand-in structure for view `vw_defaulters`
-- (See below for the actual view)
--
CREATE TABLE `vw_defaulters` (
`student_id` bigint(20)
,`register_no` varchar(30)
,`first_name` varchar(100)
,`subject_name` varchar(200)
,`total` bigint(21)
,`attended` decimal(23,0)
,`percentage` decimal(29,2)
);

-- --------------------------------------------------------

--
-- Stand-in structure for view `vw_hod_dashboard`
-- (See below for the actual view)
--
CREATE TABLE `vw_hod_dashboard` (
`department_name` varchar(150)
,`total_students` bigint(21)
,`total_staff` bigint(21)
,`overall_percentage` decimal(29,2)
);

-- --------------------------------------------------------

--
-- Stand-in structure for view `vw_live_cameras`
-- (See below for the actual view)
--
CREATE TABLE `vw_live_cameras` (
`camera_name` varchar(150)
,`room_number` varchar(20)
,`status` enum('Online','Offline','Maintenance')
,`last_checked` datetime
);

-- --------------------------------------------------------

--
-- Stand-in structure for view `vw_staff_attendance`
-- (See below for the actual view)
--
CREATE TABLE `vw_staff_attendance` (
`staff_code` varchar(30)
,`staff_name` varchar(100)
,`subject_name` varchar(200)
,`total_records` bigint(21)
);

-- --------------------------------------------------------

--
-- Stand-in structure for view `vw_staff_subject_report`
-- (See below for the actual view)
--
CREATE TABLE `vw_staff_subject_report` (
`staff_code` varchar(30)
,`first_name` varchar(100)
,`subject_name` varchar(200)
,`classes_handled` bigint(21)
,`total_present` decimal(23,0)
,`total_absent` decimal(23,0)
);

-- --------------------------------------------------------

--
-- Stand-in structure for view `vw_student_attendance`
-- (See below for the actual view)
--
CREATE TABLE `vw_student_attendance` (
`student_id` bigint(20)
,`register_no` varchar(30)
,`first_name` varchar(100)
,`subject_name` varchar(200)
,`total` bigint(21)
,`attended` decimal(23,0)
,`percentage` decimal(29,2)
);

-- --------------------------------------------------------

--
-- Stand-in structure for view `vw_student_dashboard`
-- (See below for the actual view)
--
CREATE TABLE `vw_student_dashboard` (
`id` bigint(20)
,`register_no` varchar(30)
,`first_name` varchar(100)
,`email` varchar(150)
,`overall_percentage` decimal(29,2)
);

-- --------------------------------------------------------

--
-- Stand-in structure for view `vw_subject_absentees`
-- (See below for the actual view)
--
CREATE TABLE `vw_subject_absentees` (
`subject_name` varchar(200)
,`register_no` varchar(30)
,`first_name` varchar(100)
,`attendance_date` date
);

-- --------------------------------------------------------

--
-- Stand-in structure for view `vw_unknown_faces`
-- (See below for the actual view)
--
CREATE TABLE `vw_unknown_faces` (
`id` bigint(20)
,`camera_name` varchar(150)
,`image_path` varchar(255)
,`confidence` decimal(5,2)
,`first_seen` datetime
,`last_seen` datetime
,`reviewed` tinyint(1)
);

-- --------------------------------------------------------

--
-- Table structure for table `working_days`
--

CREATE TABLE `working_days` (
  `id` bigint(20) NOT NULL,
  `academic_year_id` int(11) DEFAULT NULL,
  `work_date` date DEFAULT NULL,
  `day_name` varchar(20) DEFAULT NULL,
  `is_working` tinyint(1) DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Structure for view `vw_ai_summary`
--
DROP TABLE IF EXISTS `vw_ai_summary`;

CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `vw_ai_summary`  AS SELECT cast(`recognition_logs`.`detection_time` as date) AS `detection_date`, count(0) AS `total_detections`, sum(`recognition_logs`.`recognition_status` = 'Recognized') AS `recognized`, sum(`recognition_logs`.`recognition_status` = 'Unknown') AS `unknown_faces` FROM `recognition_logs` GROUP BY cast(`recognition_logs`.`detection_time` as date) ;

-- --------------------------------------------------------

--
-- Structure for view `vw_camera_dashboard`
--
DROP TABLE IF EXISTS `vw_camera_dashboard`;

CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `vw_camera_dashboard`  AS SELECT `c`.`id` AS `id`, `c`.`camera_name` AS `camera_name`, `cl`.`room_number` AS `room_number`, `c`.`status` AS `status`, `c`.`ip_address` AS `ip_address`, `c`.`resolution` AS `resolution`, `c`.`fps` AS `fps` FROM (`cameras` `c` left join `classrooms` `cl` on(`c`.`classroom_id` = `cl`.`id`)) ;

-- --------------------------------------------------------

--
-- Structure for view `vw_class_advisor_dashboard`
--
DROP TABLE IF EXISTS `vw_class_advisor_dashboard`;

CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `vw_class_advisor_dashboard`  AS SELECT `sec`.`section_name` AS `section_name`, count(distinct `s`.`id`) AS `total_students`, round(sum(`a`.`status` = 'Present') * 100 / count(`a`.`id`),2) AS `attendance_percentage` FROM ((`sections` `sec` join `students` `s` on(`s`.`section_id` = `sec`.`id`)) left join `attendance` `a` on(`a`.`student_id` = `s`.`id`)) GROUP BY `sec`.`id` ;

-- --------------------------------------------------------

--
-- Structure for view `vw_daily_report`
--
DROP TABLE IF EXISTS `vw_daily_report`;

CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `vw_daily_report`  AS SELECT `a`.`attendance_date` AS `attendance_date`, `sub`.`subject_name` AS `subject_name`, `sec`.`section_name` AS `section_name`, sum(`a`.`status` = 'Present') AS `present`, sum(`a`.`status` = 'Absent') AS `absent` FROM (((`attendance` `a` join `timetable` `t` on(`a`.`timetable_id` = `t`.`id`)) join `subjects` `sub` on(`t`.`subject_id` = `sub`.`id`)) join `sections` `sec` on(`t`.`section_id` = `sec`.`id`)) GROUP BY `a`.`attendance_date`, `sub`.`id`, `sec`.`id` ;

-- --------------------------------------------------------

--
-- Structure for view `vw_defaulters`
--
DROP TABLE IF EXISTS `vw_defaulters`;

CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `vw_defaulters`  AS SELECT `vw_student_attendance`.`student_id` AS `student_id`, `vw_student_attendance`.`register_no` AS `register_no`, `vw_student_attendance`.`first_name` AS `first_name`, `vw_student_attendance`.`subject_name` AS `subject_name`, `vw_student_attendance`.`total` AS `total`, `vw_student_attendance`.`attended` AS `attended`, `vw_student_attendance`.`percentage` AS `percentage` FROM `vw_student_attendance` WHERE `vw_student_attendance`.`percentage` < 75 ;

-- --------------------------------------------------------

--
-- Structure for view `vw_hod_dashboard`
--
DROP TABLE IF EXISTS `vw_hod_dashboard`;

CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `vw_hod_dashboard`  AS SELECT `d`.`department_name` AS `department_name`, count(distinct `s`.`id`) AS `total_students`, count(distinct `st`.`id`) AS `total_staff`, round(sum(`a`.`status` = 'Present') * 100 / count(`a`.`id`),2) AS `overall_percentage` FROM ((((`departments` `d` left join `sections` `sec` on(`sec`.`department_id` = `d`.`id`)) left join `students` `s` on(`s`.`section_id` = `sec`.`id`)) left join `staff` `st` on(`st`.`department_id` = `d`.`id`)) left join `attendance` `a` on(`a`.`student_id` = `s`.`id`)) GROUP BY `d`.`id` ;

-- --------------------------------------------------------

--
-- Structure for view `vw_live_cameras`
--
DROP TABLE IF EXISTS `vw_live_cameras`;

CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `vw_live_cameras`  AS SELECT `c`.`camera_name` AS `camera_name`, `cl`.`room_number` AS `room_number`, `c`.`status` AS `status`, max(`cs`.`checked_at`) AS `last_checked` FROM ((`cameras` `c` left join `classrooms` `cl` on(`c`.`classroom_id` = `cl`.`id`)) left join `camera_status` `cs` on(`c`.`id` = `cs`.`camera_id`)) GROUP BY `c`.`id` ;

-- --------------------------------------------------------

--
-- Structure for view `vw_staff_attendance`
--
DROP TABLE IF EXISTS `vw_staff_attendance`;

CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `vw_staff_attendance`  AS SELECT `st`.`staff_code` AS `staff_code`, `u`.`first_name` AS `staff_name`, `sub`.`subject_name` AS `subject_name`, count(`a`.`id`) AS `total_records` FROM ((((`attendance` `a` join `timetable` `t` on(`a`.`timetable_id` = `t`.`id`)) join `staff` `st` on(`t`.`staff_id` = `st`.`id`)) join `users` `u` on(`st`.`user_id` = `u`.`id`)) join `subjects` `sub` on(`t`.`subject_id` = `sub`.`id`)) GROUP BY `st`.`id`, `sub`.`id` ;

-- --------------------------------------------------------

--
-- Structure for view `vw_staff_subject_report`
--
DROP TABLE IF EXISTS `vw_staff_subject_report`;

CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `vw_staff_subject_report`  AS SELECT `st`.`staff_code` AS `staff_code`, `u`.`first_name` AS `first_name`, `sub`.`subject_name` AS `subject_name`, count(`a`.`id`) AS `classes_handled`, sum(`a`.`status` = 'Present') AS `total_present`, sum(`a`.`status` = 'Absent') AS `total_absent` FROM ((((`timetable` `t` join `staff` `st` on(`t`.`staff_id` = `st`.`id`)) join `users` `u` on(`st`.`user_id` = `u`.`id`)) join `subjects` `sub` on(`t`.`subject_id` = `sub`.`id`)) left join `attendance` `a` on(`t`.`id` = `a`.`timetable_id`)) GROUP BY `st`.`id`, `sub`.`id` ;

-- --------------------------------------------------------

--
-- Structure for view `vw_student_attendance`
--
DROP TABLE IF EXISTS `vw_student_attendance`;

CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `vw_student_attendance`  AS SELECT `s`.`id` AS `student_id`, `s`.`register_no` AS `register_no`, `u`.`first_name` AS `first_name`, `sub`.`subject_name` AS `subject_name`, count(`a`.`id`) AS `total`, sum(`a`.`status` = 'Present') AS `attended`, round(sum(`a`.`status` = 'Present') * 100 / count(`a`.`id`),2) AS `percentage` FROM ((((`attendance` `a` join `students` `s` on(`a`.`student_id` = `s`.`id`)) join `users` `u` on(`s`.`user_id` = `u`.`id`)) join `timetable` `t` on(`a`.`timetable_id` = `t`.`id`)) join `subjects` `sub` on(`t`.`subject_id` = `sub`.`id`)) GROUP BY `s`.`id`, `sub`.`id` ;

-- --------------------------------------------------------

--
-- Structure for view `vw_student_dashboard`
--
DROP TABLE IF EXISTS `vw_student_dashboard`;

CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `vw_student_dashboard`  AS SELECT `s`.`id` AS `id`, `s`.`register_no` AS `register_no`, `u`.`first_name` AS `first_name`, `u`.`email` AS `email`, round(sum(`a`.`status` = 'Present') * 100 / count(`a`.`id`),2) AS `overall_percentage` FROM ((`students` `s` join `users` `u` on(`s`.`user_id` = `u`.`id`)) left join `attendance` `a` on(`s`.`id` = `a`.`student_id`)) GROUP BY `s`.`id` ;

-- --------------------------------------------------------

--
-- Structure for view `vw_subject_absentees`
--
DROP TABLE IF EXISTS `vw_subject_absentees`;

CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `vw_subject_absentees`  AS SELECT `sub`.`subject_name` AS `subject_name`, `s`.`register_no` AS `register_no`, `u`.`first_name` AS `first_name`, `a`.`attendance_date` AS `attendance_date` FROM ((((`attendance` `a` join `students` `s` on(`a`.`student_id` = `s`.`id`)) join `users` `u` on(`s`.`user_id` = `u`.`id`)) join `timetable` `t` on(`a`.`timetable_id` = `t`.`id`)) join `subjects` `sub` on(`t`.`subject_id` = `sub`.`id`)) WHERE `a`.`status` = 'Absent' ;

-- --------------------------------------------------------

--
-- Structure for view `vw_unknown_faces`
--
DROP TABLE IF EXISTS `vw_unknown_faces`;

CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `vw_unknown_faces`  AS SELECT `u`.`id` AS `id`, `c`.`camera_name` AS `camera_name`, `u`.`image_path` AS `image_path`, `u`.`confidence` AS `confidence`, `u`.`first_seen` AS `first_seen`, `u`.`last_seen` AS `last_seen`, `u`.`reviewed` AS `reviewed` FROM (`unknown_faces` `u` join `cameras` `c` on(`u`.`camera_id` = `c`.`id`)) ;

--
-- Indexes for dumped tables
--

--
-- Indexes for table `academic_years`
--
ALTER TABLE `academic_years`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `academic_year` (`academic_year`);

--
-- Indexes for table `ai_model_settings`
--
ALTER TABLE `ai_model_settings`
  ADD PRIMARY KEY (`id`);

--
-- Indexes for table `ai_tracking_sessions`
--
ALTER TABLE `ai_tracking_sessions`
  ADD PRIMARY KEY (`id`),
  ADD KEY `camera_id` (`camera_id`),
  ADD KEY `student_id` (`student_id`);

--
-- Indexes for table `attendance`
--
ALTER TABLE `attendance`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `student_id` (`student_id`,`timetable_id`,`attendance_date`),
  ADD KEY `timetable_id` (`timetable_id`),
  ADD KEY `marked_by` (`marked_by`),
  ADD KEY `idx_attendance_student` (`student_id`),
  ADD KEY `idx_attendance_date` (`attendance_date`);

--
-- Indexes for table `attendance_alerts`
--
ALTER TABLE `attendance_alerts`
  ADD PRIMARY KEY (`id`),
  ADD KEY `student_id` (`student_id`),
  ADD KEY `subject_id` (`subject_id`);

--
-- Indexes for table `attendance_corrections`
--
ALTER TABLE `attendance_corrections`
  ADD PRIMARY KEY (`id`),
  ADD KEY `attendance_id` (`attendance_id`),
  ADD KEY `corrected_by` (`corrected_by`);

--
-- Indexes for table `attendance_logs`
--
ALTER TABLE `attendance_logs`
  ADD PRIMARY KEY (`id`),
  ADD KEY `attendance_id` (`attendance_id`),
  ADD KEY `student_id` (`student_id`);

--
-- Indexes for table `attendance_summary`
--
ALTER TABLE `attendance_summary`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `student_id` (`student_id`,`subject_id`,`semester_id`),
  ADD KEY `subject_id` (`subject_id`),
  ADD KEY `academic_year_id` (`academic_year_id`),
  ADD KEY `semester_id` (`semester_id`);

--
-- Indexes for table `audit_logs`
--
ALTER TABLE `audit_logs`
  ADD PRIMARY KEY (`id`),
  ADD KEY `user_id` (`user_id`);

--
-- Indexes for table `backup_logs`
--
ALTER TABLE `backup_logs`
  ADD PRIMARY KEY (`id`);

--
-- Indexes for table `cameras`
--
ALTER TABLE `cameras`
  ADD PRIMARY KEY (`id`),
  ADD KEY `vendor_id` (`vendor_id`),
  ADD KEY `idx_camera_room` (`classroom_id`);

--
-- Indexes for table `camera_assignments`
--
ALTER TABLE `camera_assignments`
  ADD PRIMARY KEY (`id`),
  ADD KEY `camera_id` (`camera_id`),
  ADD KEY `classroom_id` (`classroom_id`);

--
-- Indexes for table `camera_event_logs`
--
ALTER TABLE `camera_event_logs`
  ADD PRIMARY KEY (`id`),
  ADD KEY `camera_id` (`camera_id`);

--
-- Indexes for table `camera_health_logs`
--
ALTER TABLE `camera_health_logs`
  ADD PRIMARY KEY (`id`),
  ADD KEY `camera_id` (`camera_id`);

--
-- Indexes for table `camera_status`
--
ALTER TABLE `camera_status`
  ADD PRIMARY KEY (`id`),
  ADD KEY `camera_id` (`camera_id`);

--
-- Indexes for table `camera_vendors`
--
ALTER TABLE `camera_vendors`
  ADD PRIMARY KEY (`id`);

--
-- Indexes for table `classrooms`
--
ALTER TABLE `classrooms`
  ADD PRIMARY KEY (`id`);

--
-- Indexes for table `class_swaps`
--
ALTER TABLE `class_swaps`
  ADD PRIMARY KEY (`id`),
  ADD KEY `original_staff` (`original_staff`),
  ADD KEY `replacement_staff` (`replacement_staff`),
  ADD KEY `timetable_id` (`timetable_id`),
  ADD KEY `approved_by` (`approved_by`);

--
-- Indexes for table `daily_attendance_summary`
--
ALTER TABLE `daily_attendance_summary`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `attendance_date` (`attendance_date`,`section_id`),
  ADD KEY `department_id` (`department_id`),
  ADD KEY `section_id` (`section_id`);

--
-- Indexes for table `departments`
--
ALTER TABLE `departments`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `department_code` (`department_code`);

--
-- Indexes for table `email_queue`
--
ALTER TABLE `email_queue`
  ADD PRIMARY KEY (`id`),
  ADD KEY `student_id` (`student_id`);

--
-- Indexes for table `face_embeddings`
--
ALTER TABLE `face_embeddings`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_face_student` (`student_id`);

--
-- Indexes for table `face_registration_images`
--
ALTER TABLE `face_registration_images`
  ADD PRIMARY KEY (`id`),
  ADD KEY `session_id` (`session_id`),
  ADD KEY `student_id` (`student_id`);

--
-- Indexes for table `face_registration_sessions`
--
ALTER TABLE `face_registration_sessions`
  ADD PRIMARY KEY (`id`),
  ADD KEY `student_id` (`student_id`),
  ADD KEY `registered_by` (`registered_by`);

--
-- Indexes for table `holidays`
--
ALTER TABLE `holidays`
  ADD PRIMARY KEY (`id`),
  ADD KEY `academic_year_id` (`academic_year_id`);

--
-- Indexes for table `monthly_attendance_summary`
--
ALTER TABLE `monthly_attendance_summary`
  ADD PRIMARY KEY (`id`),
  ADD KEY `academic_year_id` (`academic_year_id`),
  ADD KEY `department_id` (`department_id`),
  ADD KEY `section_id` (`section_id`);

--
-- Indexes for table `notifications`
--
ALTER TABLE `notifications`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_notifications_user` (`user_id`);

--
-- Indexes for table `periods`
--
ALTER TABLE `periods`
  ADD PRIMARY KEY (`id`);

--
-- Indexes for table `programs`
--
ALTER TABLE `programs`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `program_code` (`program_code`);

--
-- Indexes for table `recognition_logs`
--
ALTER TABLE `recognition_logs`
  ADD PRIMARY KEY (`id`),
  ADD KEY `camera_id` (`camera_id`),
  ADD KEY `idx_recognition_time` (`detection_time`),
  ADD KEY `idx_recognition_student` (`student_id`);

--
-- Indexes for table `report_exports`
--
ALTER TABLE `report_exports`
  ADD PRIMARY KEY (`id`),
  ADD KEY `exported_by` (`exported_by`);

--
-- Indexes for table `roles`
--
ALTER TABLE `roles`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `role_name` (`role_name`);

--
-- Indexes for table `sections`
--
ALTER TABLE `sections`
  ADD PRIMARY KEY (`id`),
  ADD KEY `department_id` (`department_id`),
  ADD KEY `program_id` (`program_id`),
  ADD KEY `academic_year_id` (`academic_year_id`),
  ADD KEY `semester_id` (`semester_id`);

--
-- Indexes for table `semesters`
--
ALTER TABLE `semesters`
  ADD PRIMARY KEY (`id`),
  ADD KEY `academic_year_id` (`academic_year_id`);

--
-- Indexes for table `sms_queue`
--
ALTER TABLE `sms_queue`
  ADD PRIMARY KEY (`id`),
  ADD KEY `student_id` (`student_id`);

--
-- Indexes for table `staff`
--
ALTER TABLE `staff`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `user_id` (`user_id`),
  ADD UNIQUE KEY `staff_code` (`staff_code`),
  ADD KEY `idx_staff_department` (`department_id`);

--
-- Indexes for table `staff_sections`
--
ALTER TABLE `staff_sections`
  ADD PRIMARY KEY (`id`),
  ADD KEY `staff_id` (`staff_id`),
  ADD KEY `section_id` (`section_id`);

--
-- Indexes for table `staff_subjects`
--
ALTER TABLE `staff_subjects`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `staff_id` (`staff_id`,`subject_id`,`semester_id`),
  ADD KEY `academic_year_id` (`academic_year_id`),
  ADD KEY `semester_id` (`semester_id`);

--
-- Indexes for table `students`
--
ALTER TABLE `students`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `user_id` (`user_id`),
  ADD UNIQUE KEY `register_no` (`register_no`),
  ADD KEY `idx_students_section` (`section_id`),
  ADD KEY `idx_students_register` (`register_no`);

--
-- Indexes for table `student_attendance_history`
--
ALTER TABLE `student_attendance_history`
  ADD PRIMARY KEY (`id`),
  ADD KEY `student_id` (`student_id`),
  ADD KEY `timetable_id` (`timetable_id`),
  ADD KEY `modified_by` (`modified_by`);

--
-- Indexes for table `student_devices`
--
ALTER TABLE `student_devices`
  ADD PRIMARY KEY (`id`),
  ADD KEY `student_id` (`student_id`);

--
-- Indexes for table `student_parents`
--
ALTER TABLE `student_parents`
  ADD PRIMARY KEY (`id`),
  ADD KEY `student_id` (`student_id`);

--
-- Indexes for table `student_photo_history`
--
ALTER TABLE `student_photo_history`
  ADD PRIMARY KEY (`id`),
  ADD KEY `student_id` (`student_id`);

--
-- Indexes for table `subjects`
--
ALTER TABLE `subjects`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `subject_code` (`subject_code`),
  ADD KEY `category_id` (`category_id`),
  ADD KEY `idx_subject_department` (`department_id`),
  ADD KEY `idx_subject_code` (`subject_code`);

--
-- Indexes for table `subject_categories`
--
ALTER TABLE `subject_categories`
  ADD PRIMARY KEY (`id`);

--
-- Indexes for table `system_maintenance`
--
ALTER TABLE `system_maintenance`
  ADD PRIMARY KEY (`id`),
  ADD KEY `performed_by` (`performed_by`);

--
-- Indexes for table `system_settings`
--
ALTER TABLE `system_settings`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `setting_key` (`setting_key`);

--
-- Indexes for table `timetable`
--
ALTER TABLE `timetable`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `section_id` (`section_id`,`day_of_week`,`period_id`),
  ADD KEY `academic_year_id` (`academic_year_id`),
  ADD KEY `semester_id` (`semester_id`),
  ADD KEY `subject_id` (`subject_id`),
  ADD KEY `classroom_id` (`classroom_id`),
  ADD KEY `period_id` (`period_id`),
  ADD KEY `idx_tt_staff` (`staff_id`),
  ADD KEY `idx_tt_section` (`section_id`);

--
-- Indexes for table `timetable_history`
--
ALTER TABLE `timetable_history`
  ADD PRIMARY KEY (`id`),
  ADD KEY `timetable_id` (`timetable_id`),
  ADD KEY `modified_by` (`modified_by`);

--
-- Indexes for table `unknown_faces`
--
ALTER TABLE `unknown_faces`
  ADD PRIMARY KEY (`id`),
  ADD KEY `camera_id` (`camera_id`),
  ADD KEY `reviewed_by` (`reviewed_by`),
  ADD KEY `idx_unknown_reviewed` (`reviewed`);

--
-- Indexes for table `users`
--
ALTER TABLE `users`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `username` (`username`),
  ADD KEY `department_id` (`department_id`),
  ADD KEY `idx_users_role` (`role_id`);

--
-- Indexes for table `user_sessions`
--
ALTER TABLE `user_sessions`
  ADD PRIMARY KEY (`id`),
  ADD KEY `user_id` (`user_id`);

--
-- Indexes for table `working_days`
--
ALTER TABLE `working_days`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `academic_year_id` (`academic_year_id`,`work_date`);

--
-- AUTO_INCREMENT for dumped tables
--

--
-- AUTO_INCREMENT for table `academic_years`
--
ALTER TABLE `academic_years`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=2;

--
-- AUTO_INCREMENT for table `ai_model_settings`
--
ALTER TABLE `ai_model_settings`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=2;

--
-- AUTO_INCREMENT for table `ai_tracking_sessions`
--
ALTER TABLE `ai_tracking_sessions`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `attendance`
--
ALTER TABLE `attendance`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `attendance_alerts`
--
ALTER TABLE `attendance_alerts`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `attendance_corrections`
--
ALTER TABLE `attendance_corrections`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `attendance_logs`
--
ALTER TABLE `attendance_logs`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `attendance_summary`
--
ALTER TABLE `attendance_summary`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `audit_logs`
--
ALTER TABLE `audit_logs`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `backup_logs`
--
ALTER TABLE `backup_logs`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `cameras`
--
ALTER TABLE `cameras`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=2;

--
-- AUTO_INCREMENT for table `camera_assignments`
--
ALTER TABLE `camera_assignments`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `camera_event_logs`
--
ALTER TABLE `camera_event_logs`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `camera_health_logs`
--
ALTER TABLE `camera_health_logs`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `camera_status`
--
ALTER TABLE `camera_status`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `camera_vendors`
--
ALTER TABLE `camera_vendors`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=4;

--
-- AUTO_INCREMENT for table `classrooms`
--
ALTER TABLE `classrooms`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=4;

--
-- AUTO_INCREMENT for table `class_swaps`
--
ALTER TABLE `class_swaps`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `daily_attendance_summary`
--
ALTER TABLE `daily_attendance_summary`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `departments`
--
ALTER TABLE `departments`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=7;

--
-- AUTO_INCREMENT for table `email_queue`
--
ALTER TABLE `email_queue`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `face_embeddings`
--
ALTER TABLE `face_embeddings`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `face_registration_images`
--
ALTER TABLE `face_registration_images`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `face_registration_sessions`
--
ALTER TABLE `face_registration_sessions`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `holidays`
--
ALTER TABLE `holidays`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `monthly_attendance_summary`
--
ALTER TABLE `monthly_attendance_summary`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `notifications`
--
ALTER TABLE `notifications`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `periods`
--
ALTER TABLE `periods`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=8;

--
-- AUTO_INCREMENT for table `programs`
--
ALTER TABLE `programs`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=3;

--
-- AUTO_INCREMENT for table `recognition_logs`
--
ALTER TABLE `recognition_logs`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `report_exports`
--
ALTER TABLE `report_exports`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `roles`
--
ALTER TABLE `roles`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=7;

--
-- AUTO_INCREMENT for table `sections`
--
ALTER TABLE `sections`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=7;

--
-- AUTO_INCREMENT for table `semesters`
--
ALTER TABLE `semesters`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=5;

--
-- AUTO_INCREMENT for table `sms_queue`
--
ALTER TABLE `sms_queue`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `staff`
--
ALTER TABLE `staff`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=3;

--
-- AUTO_INCREMENT for table `staff_sections`
--
ALTER TABLE `staff_sections`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `staff_subjects`
--
ALTER TABLE `staff_subjects`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `students`
--
ALTER TABLE `students`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=4;

--
-- AUTO_INCREMENT for table `student_attendance_history`
--
ALTER TABLE `student_attendance_history`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `student_devices`
--
ALTER TABLE `student_devices`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `student_parents`
--
ALTER TABLE `student_parents`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `student_photo_history`
--
ALTER TABLE `student_photo_history`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `subjects`
--
ALTER TABLE `subjects`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=5;

--
-- AUTO_INCREMENT for table `subject_categories`
--
ALTER TABLE `subject_categories`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=6;

--
-- AUTO_INCREMENT for table `system_maintenance`
--
ALTER TABLE `system_maintenance`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `system_settings`
--
ALTER TABLE `system_settings`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=5;

--
-- AUTO_INCREMENT for table `timetable`
--
ALTER TABLE `timetable`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=2;

--
-- AUTO_INCREMENT for table `timetable_history`
--
ALTER TABLE `timetable_history`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `unknown_faces`
--
ALTER TABLE `unknown_faces`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `users`
--
ALTER TABLE `users`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=6;

--
-- AUTO_INCREMENT for table `user_sessions`
--
ALTER TABLE `user_sessions`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `working_days`
--
ALTER TABLE `working_days`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- Constraints for dumped tables
--

--
-- Constraints for table `ai_tracking_sessions`
--
ALTER TABLE `ai_tracking_sessions`
  ADD CONSTRAINT `ai_tracking_sessions_ibfk_1` FOREIGN KEY (`camera_id`) REFERENCES `cameras` (`id`),
  ADD CONSTRAINT `ai_tracking_sessions_ibfk_2` FOREIGN KEY (`student_id`) REFERENCES `students` (`id`);

--
-- Constraints for table `attendance`
--
ALTER TABLE `attendance`
  ADD CONSTRAINT `attendance_ibfk_1` FOREIGN KEY (`student_id`) REFERENCES `students` (`id`) ON DELETE CASCADE,
  ADD CONSTRAINT `attendance_ibfk_2` FOREIGN KEY (`timetable_id`) REFERENCES `timetable` (`id`),
  ADD CONSTRAINT `attendance_ibfk_3` FOREIGN KEY (`marked_by`) REFERENCES `users` (`id`);

--
-- Constraints for table `attendance_alerts`
--
ALTER TABLE `attendance_alerts`
  ADD CONSTRAINT `attendance_alerts_ibfk_1` FOREIGN KEY (`student_id`) REFERENCES `students` (`id`),
  ADD CONSTRAINT `attendance_alerts_ibfk_2` FOREIGN KEY (`subject_id`) REFERENCES `subjects` (`id`);

--
-- Constraints for table `attendance_corrections`
--
ALTER TABLE `attendance_corrections`
  ADD CONSTRAINT `attendance_corrections_ibfk_1` FOREIGN KEY (`attendance_id`) REFERENCES `attendance` (`id`),
  ADD CONSTRAINT `attendance_corrections_ibfk_2` FOREIGN KEY (`corrected_by`) REFERENCES `users` (`id`);

--
-- Constraints for table `attendance_logs`
--
ALTER TABLE `attendance_logs`
  ADD CONSTRAINT `attendance_logs_ibfk_1` FOREIGN KEY (`attendance_id`) REFERENCES `attendance` (`id`) ON DELETE CASCADE,
  ADD CONSTRAINT `attendance_logs_ibfk_2` FOREIGN KEY (`student_id`) REFERENCES `students` (`id`);

--
-- Constraints for table `attendance_summary`
--
ALTER TABLE `attendance_summary`
  ADD CONSTRAINT `attendance_summary_ibfk_1` FOREIGN KEY (`student_id`) REFERENCES `students` (`id`),
  ADD CONSTRAINT `attendance_summary_ibfk_2` FOREIGN KEY (`subject_id`) REFERENCES `subjects` (`id`),
  ADD CONSTRAINT `attendance_summary_ibfk_3` FOREIGN KEY (`academic_year_id`) REFERENCES `academic_years` (`id`),
  ADD CONSTRAINT `attendance_summary_ibfk_4` FOREIGN KEY (`semester_id`) REFERENCES `semesters` (`id`);

--
-- Constraints for table `audit_logs`
--
ALTER TABLE `audit_logs`
  ADD CONSTRAINT `audit_logs_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

--
-- Constraints for table `cameras`
--
ALTER TABLE `cameras`
  ADD CONSTRAINT `cameras_ibfk_1` FOREIGN KEY (`vendor_id`) REFERENCES `camera_vendors` (`id`),
  ADD CONSTRAINT `cameras_ibfk_2` FOREIGN KEY (`classroom_id`) REFERENCES `classrooms` (`id`);

--
-- Constraints for table `camera_assignments`
--
ALTER TABLE `camera_assignments`
  ADD CONSTRAINT `camera_assignments_ibfk_1` FOREIGN KEY (`camera_id`) REFERENCES `cameras` (`id`) ON DELETE CASCADE,
  ADD CONSTRAINT `camera_assignments_ibfk_2` FOREIGN KEY (`classroom_id`) REFERENCES `classrooms` (`id`);

--
-- Constraints for table `camera_event_logs`
--
ALTER TABLE `camera_event_logs`
  ADD CONSTRAINT `camera_event_logs_ibfk_1` FOREIGN KEY (`camera_id`) REFERENCES `cameras` (`id`);

--
-- Constraints for table `camera_health_logs`
--
ALTER TABLE `camera_health_logs`
  ADD CONSTRAINT `camera_health_logs_ibfk_1` FOREIGN KEY (`camera_id`) REFERENCES `cameras` (`id`) ON DELETE CASCADE;

--
-- Constraints for table `camera_status`
--
ALTER TABLE `camera_status`
  ADD CONSTRAINT `camera_status_ibfk_1` FOREIGN KEY (`camera_id`) REFERENCES `cameras` (`id`) ON DELETE CASCADE;

--
-- Constraints for table `class_swaps`
--
ALTER TABLE `class_swaps`
  ADD CONSTRAINT `class_swaps_ibfk_1` FOREIGN KEY (`original_staff`) REFERENCES `staff` (`id`),
  ADD CONSTRAINT `class_swaps_ibfk_2` FOREIGN KEY (`replacement_staff`) REFERENCES `staff` (`id`),
  ADD CONSTRAINT `class_swaps_ibfk_3` FOREIGN KEY (`timetable_id`) REFERENCES `timetable` (`id`),
  ADD CONSTRAINT `class_swaps_ibfk_4` FOREIGN KEY (`approved_by`) REFERENCES `users` (`id`);

--
-- Constraints for table `daily_attendance_summary`
--
ALTER TABLE `daily_attendance_summary`
  ADD CONSTRAINT `daily_attendance_summary_ibfk_1` FOREIGN KEY (`department_id`) REFERENCES `departments` (`id`),
  ADD CONSTRAINT `daily_attendance_summary_ibfk_2` FOREIGN KEY (`section_id`) REFERENCES `sections` (`id`);

--
-- Constraints for table `email_queue`
--
ALTER TABLE `email_queue`
  ADD CONSTRAINT `email_queue_ibfk_1` FOREIGN KEY (`student_id`) REFERENCES `students` (`id`);

--
-- Constraints for table `face_embeddings`
--
ALTER TABLE `face_embeddings`
  ADD CONSTRAINT `face_embeddings_ibfk_1` FOREIGN KEY (`student_id`) REFERENCES `students` (`id`) ON DELETE CASCADE;

--
-- Constraints for table `face_registration_images`
--
ALTER TABLE `face_registration_images`
  ADD CONSTRAINT `face_registration_images_ibfk_1` FOREIGN KEY (`session_id`) REFERENCES `face_registration_sessions` (`id`) ON DELETE CASCADE,
  ADD CONSTRAINT `face_registration_images_ibfk_2` FOREIGN KEY (`student_id`) REFERENCES `students` (`id`) ON DELETE CASCADE;

--
-- Constraints for table `face_registration_sessions`
--
ALTER TABLE `face_registration_sessions`
  ADD CONSTRAINT `face_registration_sessions_ibfk_1` FOREIGN KEY (`student_id`) REFERENCES `students` (`id`) ON DELETE CASCADE,
  ADD CONSTRAINT `face_registration_sessions_ibfk_2` FOREIGN KEY (`registered_by`) REFERENCES `users` (`id`);

--
-- Constraints for table `holidays`
--
ALTER TABLE `holidays`
  ADD CONSTRAINT `holidays_ibfk_1` FOREIGN KEY (`academic_year_id`) REFERENCES `academic_years` (`id`);

--
-- Constraints for table `monthly_attendance_summary`
--
ALTER TABLE `monthly_attendance_summary`
  ADD CONSTRAINT `monthly_attendance_summary_ibfk_1` FOREIGN KEY (`academic_year_id`) REFERENCES `academic_years` (`id`),
  ADD CONSTRAINT `monthly_attendance_summary_ibfk_2` FOREIGN KEY (`department_id`) REFERENCES `departments` (`id`),
  ADD CONSTRAINT `monthly_attendance_summary_ibfk_3` FOREIGN KEY (`section_id`) REFERENCES `sections` (`id`);

--
-- Constraints for table `notifications`
--
ALTER TABLE `notifications`
  ADD CONSTRAINT `notifications_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE;

--
-- Constraints for table `recognition_logs`
--
ALTER TABLE `recognition_logs`
  ADD CONSTRAINT `recognition_logs_ibfk_1` FOREIGN KEY (`camera_id`) REFERENCES `cameras` (`id`),
  ADD CONSTRAINT `recognition_logs_ibfk_2` FOREIGN KEY (`student_id`) REFERENCES `students` (`id`);

--
-- Constraints for table `report_exports`
--
ALTER TABLE `report_exports`
  ADD CONSTRAINT `report_exports_ibfk_1` FOREIGN KEY (`exported_by`) REFERENCES `users` (`id`);

--
-- Constraints for table `sections`
--
ALTER TABLE `sections`
  ADD CONSTRAINT `sections_ibfk_1` FOREIGN KEY (`department_id`) REFERENCES `departments` (`id`),
  ADD CONSTRAINT `sections_ibfk_2` FOREIGN KEY (`program_id`) REFERENCES `programs` (`id`),
  ADD CONSTRAINT `sections_ibfk_3` FOREIGN KEY (`academic_year_id`) REFERENCES `academic_years` (`id`),
  ADD CONSTRAINT `sections_ibfk_4` FOREIGN KEY (`semester_id`) REFERENCES `semesters` (`id`);

--
-- Constraints for table `semesters`
--
ALTER TABLE `semesters`
  ADD CONSTRAINT `semesters_ibfk_1` FOREIGN KEY (`academic_year_id`) REFERENCES `academic_years` (`id`) ON UPDATE CASCADE;

--
-- Constraints for table `sms_queue`
--
ALTER TABLE `sms_queue`
  ADD CONSTRAINT `sms_queue_ibfk_1` FOREIGN KEY (`student_id`) REFERENCES `students` (`id`);

--
-- Constraints for table `staff`
--
ALTER TABLE `staff`
  ADD CONSTRAINT `staff_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  ADD CONSTRAINT `staff_ibfk_2` FOREIGN KEY (`department_id`) REFERENCES `departments` (`id`);

--
-- Constraints for table `staff_sections`
--
ALTER TABLE `staff_sections`
  ADD CONSTRAINT `staff_sections_ibfk_1` FOREIGN KEY (`staff_id`) REFERENCES `staff` (`id`) ON DELETE CASCADE,
  ADD CONSTRAINT `staff_sections_ibfk_2` FOREIGN KEY (`section_id`) REFERENCES `sections` (`id`);

--
-- Constraints for table `staff_subjects`
--
ALTER TABLE `staff_subjects`
  ADD CONSTRAINT `staff_subjects_ibfk_1` FOREIGN KEY (`staff_id`) REFERENCES `staff` (`id`) ON DELETE CASCADE,
  ADD CONSTRAINT `staff_subjects_ibfk_2` FOREIGN KEY (`academic_year_id`) REFERENCES `academic_years` (`id`),
  ADD CONSTRAINT `staff_subjects_ibfk_3` FOREIGN KEY (`semester_id`) REFERENCES `semesters` (`id`);

--
-- Constraints for table `students`
--
ALTER TABLE `students`
  ADD CONSTRAINT `students_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  ADD CONSTRAINT `students_ibfk_2` FOREIGN KEY (`section_id`) REFERENCES `sections` (`id`);

--
-- Constraints for table `student_attendance_history`
--
ALTER TABLE `student_attendance_history`
  ADD CONSTRAINT `student_attendance_history_ibfk_1` FOREIGN KEY (`student_id`) REFERENCES `students` (`id`),
  ADD CONSTRAINT `student_attendance_history_ibfk_2` FOREIGN KEY (`timetable_id`) REFERENCES `timetable` (`id`),
  ADD CONSTRAINT `student_attendance_history_ibfk_3` FOREIGN KEY (`modified_by`) REFERENCES `users` (`id`);

--
-- Constraints for table `student_devices`
--
ALTER TABLE `student_devices`
  ADD CONSTRAINT `student_devices_ibfk_1` FOREIGN KEY (`student_id`) REFERENCES `students` (`id`) ON DELETE CASCADE;

--
-- Constraints for table `student_parents`
--
ALTER TABLE `student_parents`
  ADD CONSTRAINT `student_parents_ibfk_1` FOREIGN KEY (`student_id`) REFERENCES `students` (`id`) ON DELETE CASCADE;

--
-- Constraints for table `student_photo_history`
--
ALTER TABLE `student_photo_history`
  ADD CONSTRAINT `student_photo_history_ibfk_1` FOREIGN KEY (`student_id`) REFERENCES `students` (`id`) ON DELETE CASCADE;

--
-- Constraints for table `subjects`
--
ALTER TABLE `subjects`
  ADD CONSTRAINT `subjects_ibfk_1` FOREIGN KEY (`category_id`) REFERENCES `subject_categories` (`id`),
  ADD CONSTRAINT `subjects_ibfk_2` FOREIGN KEY (`department_id`) REFERENCES `departments` (`id`);

--
-- Constraints for table `system_maintenance`
--
ALTER TABLE `system_maintenance`
  ADD CONSTRAINT `system_maintenance_ibfk_1` FOREIGN KEY (`performed_by`) REFERENCES `users` (`id`);

--
-- Constraints for table `timetable`
--
ALTER TABLE `timetable`
  ADD CONSTRAINT `timetable_ibfk_1` FOREIGN KEY (`academic_year_id`) REFERENCES `academic_years` (`id`),
  ADD CONSTRAINT `timetable_ibfk_2` FOREIGN KEY (`semester_id`) REFERENCES `semesters` (`id`),
  ADD CONSTRAINT `timetable_ibfk_3` FOREIGN KEY (`section_id`) REFERENCES `sections` (`id`),
  ADD CONSTRAINT `timetable_ibfk_4` FOREIGN KEY (`subject_id`) REFERENCES `subjects` (`id`),
  ADD CONSTRAINT `timetable_ibfk_5` FOREIGN KEY (`staff_id`) REFERENCES `staff` (`id`),
  ADD CONSTRAINT `timetable_ibfk_6` FOREIGN KEY (`classroom_id`) REFERENCES `classrooms` (`id`),
  ADD CONSTRAINT `timetable_ibfk_7` FOREIGN KEY (`period_id`) REFERENCES `periods` (`id`);

--
-- Constraints for table `timetable_history`
--
ALTER TABLE `timetable_history`
  ADD CONSTRAINT `timetable_history_ibfk_1` FOREIGN KEY (`timetable_id`) REFERENCES `timetable` (`id`),
  ADD CONSTRAINT `timetable_history_ibfk_2` FOREIGN KEY (`modified_by`) REFERENCES `users` (`id`);

--
-- Constraints for table `unknown_faces`
--
ALTER TABLE `unknown_faces`
  ADD CONSTRAINT `unknown_faces_ibfk_1` FOREIGN KEY (`camera_id`) REFERENCES `cameras` (`id`),
  ADD CONSTRAINT `unknown_faces_ibfk_2` FOREIGN KEY (`reviewed_by`) REFERENCES `users` (`id`);

--
-- Constraints for table `users`
--
ALTER TABLE `users`
  ADD CONSTRAINT `users_ibfk_1` FOREIGN KEY (`role_id`) REFERENCES `roles` (`id`),
  ADD CONSTRAINT `users_ibfk_2` FOREIGN KEY (`department_id`) REFERENCES `departments` (`id`);

--
-- Constraints for table `user_sessions`
--
ALTER TABLE `user_sessions`
  ADD CONSTRAINT `user_sessions_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE;

--
-- Constraints for table `working_days`
--
ALTER TABLE `working_days`
  ADD CONSTRAINT `working_days_ibfk_1` FOREIGN KEY (`academic_year_id`) REFERENCES `academic_years` (`id`);

DELIMITER $$
--
-- Events
--
CREATE DEFINER=`root`@`localhost` EVENT `ev_daily_summary` ON SCHEDULE EVERY 1 DAY STARTS '2026-09-28 19:51:42' ON COMPLETION NOT PRESERVE ENABLE DO CALL sp_daily_summary(CURDATE())$$

DELIMITER ;
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
