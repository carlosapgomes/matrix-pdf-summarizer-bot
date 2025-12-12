import sqlite3
import threading
import time
import uuid
from enum import Enum
from dataclasses import dataclass
from typing import List, Optional
import logging

logger = logging.getLogger("matrix-pdf-bot.job_queue")


class JobStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Job:
    id: str
    filename: str
    file_url: str
    event_id: str
    room_id: str
    status: JobStatus
    created_at: float
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    file_data: Optional[bytes] = None  # Stored in memory, not in DB

    @classmethod
    def create(
        cls,
        filename: str,
        file_url: str,
        event_id: str,
        room_id: str,
        file_data: bytes,
    ) -> "Job":
        return cls(
            id=str(uuid.uuid4()),
            filename=filename,
            file_url=file_url,
            event_id=event_id,
            room_id=room_id,
            status=JobStatus.PENDING,
            created_at=time.time(),
            file_data=file_data,
        )


class JobQueue:
    def __init__(self, db_path: str = "jobs.db", max_retries: int = 3):
        self.db_path = db_path
        self.max_retries = max_retries
        self._lock = threading.Lock()
        self._init_database()

    def _init_database(self):
        """Initialize SQLite database with proper schema and indexes."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    file_url TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    room_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    completed_at REAL,
                    result TEXT,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0
                )
                """
            )
            # Create indexes for performance
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON jobs(status)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_created_at ON jobs(created_at)"
            )
            conn.commit()
            logger.info("📊 Database initialized")

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with proper timeout and row factory."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def add_job(self, job: Job) -> bool:
        """Add a new job to the queue. Returns True if successful."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    conn.execute(
                        """
                        INSERT INTO jobs (
                            id, filename, file_url, event_id, room_id, status,
                            created_at, retry_count
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            job.id,
                            job.filename,
                            job.file_url,
                            job.event_id,
                            job.room_id,
                            job.status.value,
                            job.created_at,
                            job.retry_count,
                        ),
                    )
                    conn.commit()
                    logger.info(f"➕ Added job {job.id} for file {job.filename}")
                    return True
            except sqlite3.Error as e:
                logger.error(f"❌ Failed to add job: {e}")
                return False

    def has_pending_jobs(self) -> bool:
        """Check if there are any pending jobs without locking for update."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        "SELECT 1 FROM jobs WHERE status = ? LIMIT 1",
                        (JobStatus.PENDING.value,),
                    )
                    return cursor.fetchone() is not None
            except sqlite3.Error as e:
                logger.error(f"❌ Failed to check pending jobs: {e}")
                return False

    def get_next_job(self) -> Optional[Job]:
        """Get the next pending job, mark it as processing."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    # Get the oldest pending job
                    cursor = conn.execute(
                        """
                        SELECT * FROM jobs 
                        WHERE status = ? 
                        ORDER BY created_at ASC 
                        LIMIT 1
                        """,
                        (JobStatus.PENDING.value,),
                    )
                    row = cursor.fetchone()

                    if not row:
                        return None

                    # Mark as processing
                    now = time.time()
                    conn.execute(
                        """
                        UPDATE jobs 
                        SET status = ?, started_at = ? 
                        WHERE id = ?
                        """,
                        (JobStatus.PROCESSING.value, now, row["id"]),
                    )
                    conn.commit()

                    # Convert row to Job object
                    job = Job(
                        id=row["id"],
                        filename=row["filename"],
                        file_url=row["file_url"],
                        event_id=row["event_id"],
                        room_id=row["room_id"],
                        status=JobStatus.PROCESSING,
                        created_at=row["created_at"],
                        started_at=now,
                        completed_at=row["completed_at"],
                        result=row["result"],
                        error_message=row["error_message"],
                        retry_count=row["retry_count"],
                    )

                    logger.info(f"▶️ Processing job {job.id} for file {job.filename}")
                    return job

            except sqlite3.Error as e:
                logger.error(f"❌ Failed to get next job: {e}")
                return None

    def complete_job(self, job_id: str, result: str) -> bool:
        """Mark a job as completed with result."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    conn.execute(
                        """
                        UPDATE jobs 
                        SET status = ?, completed_at = ?, result = ? 
                        WHERE id = ?
                        """,
                        (JobStatus.COMPLETED.value, time.time(), result, job_id),
                    )
                    conn.commit()
                    logger.info(f"✅ Completed job {job_id}")
                    return True
            except sqlite3.Error as e:
                logger.error(f"❌ Failed to complete job: {e}")
                return False

    def fail_job(self, job_id: str, error_message: str) -> bool:
        """Mark a job as failed or retry if retries available."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    # Get current retry count
                    cursor = conn.execute(
                        "SELECT retry_count FROM jobs WHERE id = ?", (job_id,)
                    )
                    row = cursor.fetchone()

                    if not row:
                        logger.error(f"❌ Job {job_id} not found for failure")
                        return False

                    current_retries = row["retry_count"]

                    if current_retries < self.max_retries:
                        # Retry the job
                        new_retry_count = current_retries + 1
                        conn.execute(
                            """
                            UPDATE jobs 
                            SET status = ?, retry_count = ?, error_message = ?, started_at = NULL
                            WHERE id = ?
                            """,
                            (
                                JobStatus.PENDING.value,
                                new_retry_count,
                                error_message,
                                job_id,
                            ),
                        )
                        logger.info(
                            f"🔄 Retrying job {job_id} (attempt {new_retry_count}/{self.max_retries})"
                        )
                    else:
                        # Mark as permanently failed
                        conn.execute(
                            """
                            UPDATE jobs 
                            SET status = ?, completed_at = ?, error_message = ?
                            WHERE id = ?
                            """,
                            (
                                JobStatus.FAILED.value,
                                time.time(),
                                error_message,
                                job_id,
                            ),
                        )
                        logger.error(
                            f"💥 Job {job_id} failed permanently after {self.max_retries} retries"
                        )

                    conn.commit()
                    return True

            except sqlite3.Error as e:
                logger.error(f"❌ Failed to handle job failure: {e}")
                return False

    def get_completed_jobs(self) -> List[Job]:
        """Get all completed jobs."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        """
                        SELECT * FROM jobs 
                        WHERE status = ? 
                        ORDER BY completed_at ASC
                        """,
                        (JobStatus.COMPLETED.value,),
                    )

                    jobs = []
                    for row in cursor.fetchall():
                        job = Job(
                            id=row["id"],
                            filename=row["filename"],
                            file_url=row["file_url"],
                            event_id=row["event_id"],
                            room_id=row["room_id"],
                            status=JobStatus.COMPLETED,
                            created_at=row["created_at"],
                            started_at=row["started_at"],
                            completed_at=row["completed_at"],
                            result=row["result"],
                            error_message=row["error_message"],
                            retry_count=row["retry_count"],
                        )
                        jobs.append(job)

                    return jobs

            except sqlite3.Error as e:
                logger.error(f"❌ Failed to get completed jobs: {e}")
                return []

    def get_failed_jobs(self) -> List[Job]:
        """Get all permanently failed jobs."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        """
                        SELECT * FROM jobs 
                        WHERE status = ? 
                        ORDER BY completed_at ASC
                        """,
                        (JobStatus.FAILED.value,),
                    )

                    jobs = []
                    for row in cursor.fetchall():
                        job = Job(
                            id=row["id"],
                            filename=row["filename"],
                            file_url=row["file_url"],
                            event_id=row["event_id"],
                            room_id=row["room_id"],
                            status=JobStatus.FAILED,
                            created_at=row["created_at"],
                            started_at=row["started_at"],
                            completed_at=row["completed_at"],
                            result=row["result"],
                            error_message=row["error_message"],
                            retry_count=row["retry_count"],
                        )
                        jobs.append(job)

                    return jobs

            except sqlite3.Error as e:
                logger.error(f"❌ Failed to get failed jobs: {e}")
                return []

    def remove_job(self, job_id: str) -> bool:
        """Remove a job from the queue (used after sending results)."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
                    conn.commit()
                    logger.info(f"🗑️ Removed job {job_id}")
                    return True
            except sqlite3.Error as e:
                logger.error(f"❌ Failed to remove job: {e}")
                return False

    def cleanup_old_jobs(self, hours_old: int = 24) -> int:
        """Remove completed/failed jobs older than specified hours."""
        cutoff_time = time.time() - (hours_old * 3600)

        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        """
                        DELETE FROM jobs 
                        WHERE status IN (?, ?) AND completed_at < ?
                        """,
                        (
                            JobStatus.COMPLETED.value,
                            JobStatus.FAILED.value,
                            cutoff_time,
                        ),
                    )
                    conn.commit()
                    deleted_count = cursor.rowcount
                    if deleted_count > 0:
                        logger.info(f"🧹 Cleaned up {deleted_count} old jobs")
                    return deleted_count

            except sqlite3.Error as e:
                logger.error(f"❌ Failed to cleanup old jobs: {e}")
                return 0

    def get_queue_stats(self) -> dict:
        """Get statistics about the job queue."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        """
                        SELECT status, COUNT(*) as count 
                        FROM jobs 
                        GROUP BY status
                        """
                    )

                    stats = {status.value: 0 for status in JobStatus}
                    for row in cursor.fetchall():
                        stats[row["status"]] = row["count"]

                    return stats

            except sqlite3.Error as e:
                logger.error(f"❌ Failed to get queue stats: {e}")
                return {status.value: 0 for status in JobStatus}
