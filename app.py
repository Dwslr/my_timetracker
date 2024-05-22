import logging
import psycopg2
from datetime import datetime
import sys
import tkinter as tk
from tkinter import messagebox
import threading
import time

# custom import from my private config file to get DB host, port etc
from f_db_config import db_host, db_port, db_name, db_user, db_password


today_date = datetime.today().date()
log_dir = "my_timetracker/logs"

# Create and configure logger
logger = logging.getLogger(f"my_timetracker_log-{today_date}")
logger.setLevel(logging.INFO)

# Create file handler which logs even debug messages
handler = logging.FileHandler(f"{log_dir}/my_timetracker_log-{today_date}.log")

# Create formatter and add it to the handlers
formatter = logging.Formatter("%(name)s %(asctime)s %(levelname)s %(message)s")
handler.setFormatter(formatter)

# Add the handler to the logger
logger.addHandler(handler)


logger.info("")
logger.info(f" --- STARTING THE CUSTOM LOGGER FOR MY TIMETRACKER APPLICATION --- ")


class Database:
    def __new__(cls, *args, **kwargs):
        if not hasattr(cls, "instance"):
            cls.instance = super().__new__(cls)
        return cls.instance

    def __init__(self, host, port, db, user, pss):
        try:
            self.con = psycopg2.connect(
                host=host, port=port, database=db, user=user, password=pss
            )
            self.cur = self.con.cursor()
            logger.info("Connected to database.")
        except Exception as e:
            logger.error(f"Error connecting to database: {e}")
            raise e  # Raise the exception for the GUI to handle

    def get_mtt_tables(self):
        try:
            self.cur.execute(
                """SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name LIKE 'mtt%'"""
            )
            tables = self.cur.fetchall()
            logger.info(f"The database contains {len(tables)} 'mtt' tables: {tables}")
            return tables
        except psycopg2.Error as e:
            logger.error(f"Error selecting tables from the database: {e}")

    def create_table(self, table_name, columns_query):
        logger.info(f"Creating table '{table_name}'...")
        try:
            create_table_query = f"""
                CREATE TABLE {table_name} (
                    {columns_query}
                )
            """
            self.cur.execute(create_table_query)
            self.con.commit()
            logger.info(f"Table '{table_name}' created successfully!")
        except psycopg2.errors.DuplicateTable:
            logger.info(f"Table '{table_name}' already exists.")
        except psycopg2.Error as er:
            logger.error(f"Error creating table '{table_name}': {er}")

    def drop_table(self, table_name):
        logger.info(f"Dropping table '{table_name}'...")
        try:
            drop_table_query = f"""
            DROP TABLE IF EXISTS {table_name}
            """
            self.cur.execute(drop_table_query)
            self.con.commit()
            logger.info(f"Table '{table_name}' deleted!")
        except psycopg2.Error as er:
            logger.error(f"Error deleting table '{table_name}': {er}")

    def add_user(self, username):
        try:
            insert_query = (
                """INSERT INTO mtt_users (username) VALUES (%s) RETURNING id"""
            )
            self.cur.execute(insert_query, (username,))
            self.con.commit()
            user_id = self.cur.fetchone()[0]
            logger.info(f"User '{username}' added successfully with ID {user_id}.")
            return user_id
        except psycopg2.errors.UniqueViolation:
            logger.error(f"User '{username}' already exists.")
            self.con.rollback()
        except psycopg2.Error as e:
            logger.error(f"Error adding user '{username}': {e}")
            self.con.rollback()
        return None

    def start_task(self, user_id, task_name):
        try:
            insert_query = """INSERT INTO mtt_tasks (user_id, task, start)
                            VALUES (%s, %s, CURRENT_TIMESTAMP)"""
            self.cur.execute(insert_query, (user_id, task_name))
            self.con.commit()
            logger.info(
                f"Task '{task_name}' for user ID '{user_id}' started successfully."
            )
        except psycopg2.errors.UniqueViolation:
            logger.error(f"Task '{task_name}' for user ID '{user_id}' already exists.")
            self.con.rollback()
        except psycopg2.Error as e:
            logger.error(
                f"Error starting task '{task_name}' for user ID '{user_id}': {e}"
            )
            self.con.rollback()
            sys.exit()

    def finish_task(self, user_id, task_name):
        try:
            update_query = """UPDATE mtt_tasks
                              SET finish = CURRENT_TIMESTAMP
                              WHERE user_id = %s AND task = %s AND finish IS NULL"""
            self.cur.execute(update_query, (user_id, task_name))
            self.con.commit()
            logger.info(
                f"Task '{task_name}' for user ID '{user_id}' finished successfully."
            )
        except psycopg2.Error as e:
            logger.error(
                f"Error finishing task '{task_name}' for user ID '{user_id}': {e}"
            )
            self.con.rollback()

    def __del__(self):
        try:
            self.cur.close()
            self.con.close()
            logger.info("Database connection closed.")
        except Exception as e:
            logger.error(f"Error closing database connection: {e}")

    def get_or_create_user(self, username):
        try:
            # Check if the user already exists in the database
            self.cur.execute(
                "SELECT id FROM mtt_users WHERE username = %s", (username,)
            )
            user_row = self.cur.fetchone()
            if user_row:
                user_id = user_row[0]
                logger.info(f"User '{username}' already exists with ID '{user_id}'.")
            else:
                # If the user does not exist, add them to the database
                user_id = self.add_user(username)
        except psycopg2.Error as e:
            logger.error(f"Error getting or creating user '{username}': {e}")
            self.con.rollback()
            user_id = None

        return user_id


class TimerApp:
    def __init__(self, db):
        try:
            self.db = db
        except Exception as e:
            messagebox.showerror(
                "Database Error", f"Could not connect to the database: {e}"
            )
            sys.exit(1)

        self.user_id = None
        self.root = tk.Tk()  # Initialize the Tk root window
        self.root.title("MyTimeTracker DMTT")

        self.user_label = tk.Label(self.root, text="Username:")
        self.user_label.pack()
        self.user_entry = tk.Entry(self.root)
        self.user_entry.pack()
        self.user_button = tk.Button(self.root, text="Submit", command=self.setup_user)
        self.user_button.pack()

        self.task_label = tk.Label(self.root, text="Task Name:")
        self.task_label.pack()
        self.task_entry = tk.Entry(self.root)
        self.task_entry.pack()

        self.start_button = tk.Button(
            self.root, text="Start Task", command=self.start_task, state=tk.DISABLED
        )
        self.start_button.pack()

        self.timer_label = tk.Label(self.root, text="00:00:00")
        self.timer_label.pack()

        self.stop_button = tk.Button(
            self.root, text="Stop Task", command=self.stop_task, state=tk.DISABLED
        )
        self.stop_button.pack()

        self.timer_running = False
        self.start_time = None
        self.elapsed_time = 0

    def run(self):
        self.root.mainloop()

    def setup_user(self):
        username = self.user_entry.get()
        if not username:
            messagebox.showerror("Input Error", "Username cannot be empty.")
            return

        user_id = self.db.get_or_create_user(username)
        if user_id is not None:
            self.user_id = user_id
            self.user_entry.config(state=tk.DISABLED)
            self.user_button.config(state=tk.DISABLED)
            self.start_button.config(state=tk.NORMAL)
            logger.info(f"User '{username}' set up with ID '{self.user_id}'.")
        else:
            messagebox.showerror("Database Error", "Could not set up user.")

    def start_task(self):
        task_name = self.task_entry.get()
        if not task_name:
            messagebox.showerror("Input Error", "Task name cannot be empty.")
            return

        self.db.start_task(self.user_id, task_name)
        self.start_time = datetime.now()
        self.timer_running = True
        self.timer_thread = threading.Thread(target=self.update_timer)
        self.timer_thread.daemon = True
        self.timer_thread.start()
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        logger.info(f"Task '{task_name}' started at {self.start_time}")

    def update_timer(self):
        while self.timer_running:
            elapsed_time = datetime.now() - self.start_time
            hours, remainder = divmod(elapsed_time.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            time_string = f"{hours:02}:{minutes:02}:{seconds:02}"
            self.timer_label.config(text=time_string)
            time.sleep(1)  # Sleep for a second to update the timer every second

    def stop_task(self):
        self.timer_running = False
        elapsed_time = datetime.now() - self.start_time
        self.elapsed_time = elapsed_time.total_seconds()
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)

        task_name = self.task_entry.get()
        self.db.finish_task(self.user_id, task_name)

        logger.info(f"Task '{task_name}' stopped after {self.elapsed_time} seconds")
        messagebox.showinfo("Task Completed", f"Task completed in {str(elapsed_time)}.")


db = Database(db_host, db_port, db_name, db_user, db_password)

db.get_mtt_tables()

# db.create_table(
#     "mtt_users",
#     "id SERIAL PRIMARY KEY, username VARCHAR(50) UNIQUE, email VARCHAR(50) UNIQUE",
# )

# db.create_table(
#     "mtt_tasks",
#     """id SERIAL PRIMARY KEY,
#         user_id INT,
#         task VARCHAR(50),
#         start TIMESTAMP,
#         finish TIMESTAMP,
#         constraint fk_users
#             foreign key (user_id)
#             references mtt_users(id)""",
# )

# db.drop_table('mtt_tasks')
# db.drop_table('mtt_users')

db.add_user("Dwisler")
# db.start_task(1, "Learning English")


# Start the TimerApp
app = TimerApp(db)
app.run()


# class Database:
#     def __new__(cls, *args, **kwargs):
#         if not hasattr(cls, "instance"):
#             cls.instance = super().__new__(cls)
#         return cls.instance

#     def __init__(self, host, port, db, user, pss):
#         try:
#             self.con = psycopg2.connect(
#                 host=host, port=port, database=db, user=user, password=pss
#             )
#             self.cur = self.con.cursor()
#             logger.info("Connected to database.")
#         except Exception as e:
#             logger.error(f"Error connecting to database: {e}")
#             sys.exit(1)

#     def __del__(self):
#         try:
#             self.cur.close()
#             self.con.close()
#             logger.info("Database connection closed.")
#         except Exception as e:
#             logger.error(f"Error closing database connection: {e}")

#     def get_all_tables(self):
#         try:
#             self.cur.execute(
#                 """SELECT table_name
#                     FROM information_schema.tables
#                     WHERE table_schema = 'public' AND table_name LIKE 'pp%'"""
#             )
#             tables = self.cur.fetchall()
#             logger.info(
#                 f"The database contains {len(tables)} tables named python_project: {tables}"
#             )
#             return tables
#         except psycopg2.Error as e:
#             logger.error(f"Error selecting tables from the database: {e}")

#     def create_table(self, table_name):
#         logger.info("Creating table stage...")
#         try:
#             self.cur.execute(
#                 """
#                 SELECT EXISTS (
#                     SELECT 1
#                     FROM information_schema.tables
#                     WHERE table_schema = 'public'
#                     AND table_name = %s
#                 )
#                 """,
#                 (table_name,),
#             )
#             table_exists = self.cur.fetchone()[0]

#             if not table_exists:
#                 create_table_query = f"""
#                     CREATE TABLE {table_name} (
#                         id SERIAL PRIMARY KEY,
#                         user_id VARCHAR(255),
#                         oauth_consumer_key VARCHAR(255),
#                         lis_result_sourcedid VARCHAR(255),
#                         lis_outcome_service_url VARCHAR(255),
#                         is_correct INTEGER,
#                         attempt_type VARCHAR(255),
#                         created_at VARCHAR(255)
#                     )
#                 """

#                 self.cur.execute(create_table_query)
#                 self.con.commit()
#                 logger.info(f"Table '{table_name}' created successfully!")
#             else:
#                 logger.info(f"Table '{table_name}' already exists.")
#         except psycopg2.Error as er:
#             logger.error(f"Error creating table '{table_name}': {er}")

#     def load_data_to_db(self, table_name, vdata):
#         logger.info("Loading data to the db table...")
#         try:
#             skipped_count = 0
#             for idx, row in enumerate(vdata, start=1):
#                 # check if the data has already been loaded
#                 self.cur.execute(
#                     f"""SELECT COUNT(*)
#                         FROM {table_name}
#                         WHERE (user_id = %s or user_id is Null) AND created_at = %s""",
#                     (row["user_id"], row["created_at"]),
#                 )
#                 count = self.cur.fetchone()[0]
#                 skipped_count += count  # Update the skipped count

#                 if count == 0:
#                     # data has not been loaded previously, insert it into the database
#                     self.cur.execute(
#                         f"""
#                         INSERT INTO {table_name}
#                         (user_id, oauth_consumer_key, lis_result_sourcedid, lis_outcome_service_url, is_correct, attempt_type, created_at)
#                         VALUES (%s, %s, %s, %s, %s, %s, %s)
#                     """,
#                         (
#                             row["user_id"],
#                             row["oauth_consumer_key"],
#                             row["lis_result_sourcedid"],
#                             row["lis_outcome_service_url"],
#                             row["is_correct"],
#                             row["attempt_type"],
#                             row["created_at"],
#                         ),
#                     )

#             logger.info(
#                 f"Checking previously loaded data found and skipped {skipped_count} lines."
#             )

#             self.con.commit()
#             logger.info("Data loaded to the database successfully!")
#         except psycopg2.Error as er:
#             logger.error(f"Error loading data to the database: {er}")

#     def select_query(self, table_name, sql_query):
#         try:
#             self.cur = self.con.cursor(cursor_factory=RealDictCursor)
#             self.cur.execute(f"""{sql_query}""")
#             result = self.cur.fetchall()
#             logger.info(
#                 f"Select query for '{table_name}' table completed successfully."
#             )
#             return result
#         except psycopg2.Error as e:
#             logger.error(f"Error select query: {e}")


# logger.info(f" --- REACHED THE END OF THE MODULE --- ")
