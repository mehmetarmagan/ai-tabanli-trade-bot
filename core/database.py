import sqlite3
import structlog
from datetime import datetime, timezone

logger = structlog.get_logger()


class SignalDatabase:
    def __init__(self, db_name: str = "ceo_trade_signals.db"):
        self.db_name = db_name
        self._connection = None
        if self.db_name == ":memory:":
            self._connection = sqlite3.connect(self.db_name)
            self._connection.row_factory = sqlite3.Row
        self.init_db()

    def get_connection(self):
        if self.db_name == ":memory:" and self._connection is not None:
            return self._connection
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """Sinyaller ve işlemler için veritabanı tablolarını oluşturur."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    symbol TEXT,
                    action TEXT,
                    entry_price REAL,
                    stop_loss REAL,
                    tp1 REAL,
                    tp2 REAL,
                    tp3 REAL,
                    status TEXT DEFAULT 'PENDING'
                )
                """
            )
            conn.commit()
        logger.info("database_initialized", db_name=self.db_name)

    def save_signal(
        self,
        symbol: str,
        action: str,
        entry_price: float,
        stop_loss: float,
        tp1: float,
        tp2: float,
        tp3: float,
    ):
        """Üretilen yeni bir sinyali veritabanına kaydeder."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO signals (timestamp, symbol, action, entry_price, stop_loss, tp1, tp2, tp3, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
                    """,
                    (timestamp, symbol, action, entry_price, stop_loss, tp1, tp2, tp3),
                )
                conn.commit()
            logger.info("signal_saved_to_db", symbol=symbol, action=action)
        except Exception as e:
            logger.error("database_save_error", error=str(e))

    def get_recent_signals(self, limit: int = 50):
        """Son kaydedilen sinyalleri getirir."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM signals ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            return cursor.fetchall()

    def update_signal_status(self, signal_id: int, status: str) -> bool:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE signals SET status = ? WHERE id = ?",
                    (status, signal_id),
                )
                conn.commit()
            return True
        except Exception as exc:
            logger.error("database_update_status_error", error=str(exc), signal_id=signal_id)
            return False

    def get_signal_by_id(self, signal_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM signals WHERE id = ?", (signal_id,))
            row = cursor.fetchone()
            return dict(row) if row is not None else None
