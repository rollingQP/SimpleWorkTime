import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import sqlite3
from datetime import datetime, date, timedelta
import calendar
import os
import sys


class ConfigManager:
    """Handles saving and loading the application configuration, like the DB path."""

    def __init__(self):
        # Determine the path for the config file, works for both script and PyInstaller
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.join(base_path, 'config.txt')

    def load_db_path(self):
        """Loads the database path from the config file."""
        try:
            with open(self.config_path, 'r') as f:
                path = f.readline().strip()
                if path and os.path.exists(path):
                    return path
        except FileNotFoundError:
            return None  # Config file doesn't exist yet
        return None

    def save_db_path(self, path):
        """Saves the given database path to the config file."""
        with open(self.config_path, 'w') as f:
            f.write(path)


class DatabaseManager:
    """处理所有数据库操作"""

    def __init__(self, db_path=None):
        final_db_path = db_path

        # If no valid path is provided, fall back to the default 'work_log.db'
        # next to the executable or script.
        if not final_db_path:
            if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
                base_path = os.path.dirname(sys.executable)
            else:
                base_path = os.path.dirname(os.path.abspath(__file__))
            final_db_path = os.path.join(base_path, 'work_log.db')

        self.db_path = final_db_path
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.cursor = self.conn.cursor()
            self.create_table()
            print(f"Successfully connected to database: {self.db_path}")
        except sqlite3.Error as e:
            messagebox.showerror("Database Error", f"Could not connect to database at:\n{self.db_path}\n\nError: {e}")
            # Raise an exception to be caught by the app, preventing it from starting with a bad DB.
            raise ConnectionError(f"Failed to connect to {self.db_path}") from e

    def create_table(self):
        """创建用于存储时间记录的表"""
        self.cursor.execute('''
                            CREATE TABLE IF NOT EXISTS time_log
                            (
                                id
                                INTEGER
                                PRIMARY
                                KEY
                                AUTOINCREMENT,
                                checkpoint
                                TEXT
                                NOT
                                NULL
                                UNIQUE
                            )
                            ''')
        self.conn.commit()

    def add_checkpoint(self, dt_obj=None):
        """添加一个新的时间戳检查点"""
        if dt_obj is None:
            dt_obj = datetime.now()
        dt_string = dt_obj.strftime('%Y-%m-%d %H:%M:%S')
        try:
            self.cursor.execute("INSERT INTO time_log (checkpoint) VALUES (?)", (dt_string,))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            # 防止在同一秒内重复添加
            print(f"警告：时间点 {dt_string} 已存在。")
            return False

    def get_checkpoints_for_day(self, target_date):
        """获取指定日期的所有检查点"""
        date_str = target_date.strftime('%Y-%m-%d')
        self.cursor.execute(
            "SELECT checkpoint FROM time_log WHERE strftime('%Y-%m-%d', checkpoint) = ? ORDER BY checkpoint ASC",
            (date_str,))
        return [datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S') for row in self.cursor.fetchall()]

    def get_checkpoints_for_range(self, start_date, end_date):
        """获取指定日期范围内的所有检查点"""
        start_str = start_date.strftime('%Y-%m-%d 00:00:00')
        end_str = end_date.strftime('%Y-%m-%d 23:59:59')
        self.cursor.execute("SELECT checkpoint FROM time_log WHERE checkpoint BETWEEN ? AND ? ORDER BY checkpoint ASC",
                            (start_str, end_str))
        return [datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S') for row in self.cursor.fetchall()]

    def delete_checkpoint(self, dt_obj):
        """删除一个指定的时间点"""
        dt_string = dt_obj.strftime('%Y-%m-%d %H:%M:%S')
        self.cursor.execute("DELETE FROM time_log WHERE checkpoint = ?", (dt_string,))
        self.conn.commit()
        return self.cursor.rowcount > 0

    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
            print(f"Database connection closed for: {self.db_path}")


class TimeTrackerApp:
    def __init__(self, root, db_manager, config_manager):
        self.root = root
        self.db = db_manager
        self.config = config_manager
        self.root.title("工时打卡器")
        self.root.geometry("350x300")
        self.root.resizable(False, False)

        self.update_job = None
        self.stats_window = None
        self.manual_entry_window = None

        self.setup_ui()
        self.load_initial_state()
        self.root.protocol("WM_DELETE_WINDOW", self.clean_up_on_exit)

    def clean_up_on_exit(self):
        """关闭窗口时停止UI更新定时器并销毁窗口"""
        self.stop_ui_update_timer()
        self.db.close()
        self.root.destroy()

    def setup_ui(self):
        """设置主界面UI"""
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Select Database...", command=self.select_database_file)
        file_menu.add_command(label="Show Database Path", command=self.show_database_path)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.clean_up_on_exit)
        menubar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menubar)

        main_frame = ttk.Frame(self.root, padding=20)
        main_frame.pack(expand=True, fill="both")

        # --- 时间显示 ---
        self.total_time_label = ttk.Label(main_frame, text="今日总工时: 00:00:00", font=("Helvetica", 12))
        self.total_time_label.pack(pady=5)

        # --- 状态显示 ---
        self.status_label = ttk.Label(main_frame, text="状态: 已停止", font=("Helvetica", 10), foreground="red")
        self.status_label.pack(pady=5)

        # --- 主按钮 ---
        self.toggle_button = ttk.Button(main_frame, text="上班打卡", command=self.toggle_timer, width=20)
        style = ttk.Style()
        style.configure('TButton', font=('Helvetica', 12), padding=10)
        self.toggle_button.pack(pady=20)

        # 添加一个用于提示信息的小标签
        self.info_label = ttk.Label(main_frame, text="", foreground="gray")
        self.info_label.pack(pady=5)

        # --- 底部功能按钮 ---
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(side="bottom", pady=10)
        ttk.Button(button_frame, text="查看统计", command=self.open_stats_window).pack(side="left", padx=10)
        ttk.Button(button_frame, text="修改数据", command=self.open_manual_entry_window).pack(side="left", padx=10)

    def select_database_file(self):
        """Opens a file dialog to select and load a new database file without restarting."""
        filepath = filedialog.askopenfilename(
            title="Select a Database File",
            filetypes=[("Database Files", "*.db"), ("All Files", "*.*")]
        )
        if filepath and filepath != self.db.db_path:
            self.config.save_db_path(filepath)
            self.reload_with_new_database(filepath)

    def show_database_path(self):
        """显示当前数据库路径"""
        messagebox.showinfo(
            "数据库路径",
            f"当前数据库文件位置:\n{self.db.db_path}"
        )

    def reload_with_new_database(self, new_db_path):
        """Closes the old DB, opens a new one, and refreshes the entire application state."""
        print("Reloading application with new database...")
        # 1. Stop any running timers
        self.stop_ui_update_timer()

        # 2. Close any open child windows to prevent them from using the old DB
        if self.stats_window and self.stats_window.winfo_exists():
            self.stats_window.destroy()
            self.stats_window = None
        if self.manual_entry_window and self.manual_entry_window.winfo_exists():
            self.manual_entry_window.destroy()
            self.manual_entry_window = None

        # 3. Close the current database connection
        self.db.close()

        # 4. Connect to the new database
        try:
            self.db = DatabaseManager(db_path=new_db_path)
            messagebox.showinfo(
                "Database Changed",
                f"Successfully loaded database:\n{os.path.basename(new_db_path)}"
            )
        except ConnectionError:
            # If the new DB is invalid, try to revert to the previous one.
            messagebox.showerror("Error", f"Could not load the selected database. Reverting to the previous one.")
            self.db = DatabaseManager(db_path=self.db.db_path)  # Reconnect to old DB

        # 5. Refresh the main UI with data from the new database
        self.load_initial_state()

    def load_initial_state(self):
        """程序启动时加载今天的状态"""
        self.update_display()

    def toggle_timer(self):
        """处理开始/停止计时器按钮的点击事件"""
        self.db.add_checkpoint()
        self.update_display()

    def update_display(self):
        """更新界面上所有动态信息"""
        today = date.today()
        checkpoints = self.db.get_checkpoints_for_day(today)
        total_seconds_today = self.calculate_worked_seconds(checkpoints)

        if len(checkpoints) % 2 != 0:  # 奇数个点，表示正在计时
            self.is_running = True
            self.last_start_time = checkpoints[-1]
            self.status_label.config(text="状态: 工作中...", foreground="green")
            self.toggle_button.config(text="下班打卡")
            self.info_label.config(text="现在可关闭窗口，不影响计时。")
            self.start_ui_update_timer()
        else:  # 偶数个点，表示已停止
            self.is_running = False
            self.last_start_time = None
            self.status_label.config(text="状态: 已停止", foreground="red")
            self.toggle_button.config(text="上班打卡")
            self.info_label.config(text="")
            self.stop_ui_update_timer()

        self.total_time_label.config(text=f"今日总工时: {self.format_seconds(total_seconds_today)}")

    def start_ui_update_timer(self):
        """启动一个每秒更新界面的定时器"""
        if self.update_job is None:
            self.update_clock()

    def stop_ui_update_timer(self):
        """停止界面更新定时器"""
        if self.update_job:
            self.root.after_cancel(self.update_job)
            self.update_job = None

    def update_clock(self):
        """每秒更新一次时间显示"""
        if self.is_running and self.last_start_time:
            today = date.today()
            checkpoints = self.db.get_checkpoints_for_day(today)
            total_seconds = self.calculate_worked_seconds(checkpoints, include_current=True)
            self.total_time_label.config(text=f"今日总工时: {self.format_seconds(total_seconds)}")
        self.update_job = self.root.after(1000, self.update_clock)

    def calculate_worked_seconds(self, checkpoints, include_current=False):
        """根据时间点列表计算总工作秒数"""
        total_seconds = 0
        for i in range(0, len(checkpoints) - 1, 2):
            total_seconds += (checkpoints[i + 1] - checkpoints[i]).total_seconds()

        # 如果正在计时，加上当前正在进行的这一段的时间
        if include_current and len(checkpoints) % 2 != 0:
            total_seconds += (datetime.now() - checkpoints[-1]).total_seconds()

        return total_seconds

    def format_seconds(self, seconds):
        """将秒数格式化为 HH:MM:SS"""
        s = int(seconds);
        h, s = divmod(s, 3600);
        m, s = divmod(s, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def open_stats_window(self):
        """打开统计窗口"""
        if self.stats_window and self.stats_window.winfo_exists():
            self.stats_window.lift()
            self.stats_window.generate_report()
        else:
            self.stats_window = StatsWindow(self.root, self, self.db, self.format_seconds)

    def open_manual_entry_window(self, parent_win=None, target_date=None):
        """打开手动补录窗口"""
        if parent_win is None: parent_win = self.root

        if self.manual_entry_window and self.manual_entry_window.winfo_exists():
            self.manual_entry_window.lift()
        else:
            win = ManualEntryWindow(parent_win, self.db, target_date=target_date)
            self.manual_entry_window = win.win  # Keep a reference to the Toplevel window
            if win.dirty:
                self.load_initial_state()


class DatePicker(tk.Toplevel):
    """一个简单的日历日期选择器窗口"""

    def __init__(self, parent, entry_widget):
        super().__init__(parent)
        self.withdraw()
        self.transient(parent)
        self.title("选择日期")
        self.entry_widget = entry_widget
        self.selected_date = None

        parent.update_idletasks()
        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        new_x = parent_x + parent_width + 10
        new_y = parent_y + 30
        self.geometry(f"+{new_x}+{new_y}")

        try:
            self.current_date = datetime.strptime(entry_widget.get(), '%Y-%m-%d').date()
        except ValueError:
            self.current_date = date.today()

        self.cal = calendar.Calendar()
        self.setup_ui()
        self.update_calendar()
        self.deiconify()
        self.grab_set()

    def setup_ui(self):
        nav_frame = ttk.Frame(self)
        nav_frame.pack(pady=5)
        ttk.Button(nav_frame, text="<", command=self.prev_month, width=4).pack(side="left", padx=5)
        self.month_year_label = ttk.Label(nav_frame, width=18, anchor="center")
        self.month_year_label.pack(side="left")
        ttk.Button(nav_frame, text=">", command=self.next_month, width=4).pack(side="left", padx=5)
        self.cal_frame = ttk.Frame(self, padding=5)
        self.cal_frame.pack()

    def update_calendar(self):
        for widget in self.cal_frame.winfo_children():
            widget.destroy()

        self.month_year_label.config(text=self.current_date.strftime('%Y 年 %m 月'))
        month_days = self.cal.monthdayscalendar(self.current_date.year, self.current_date.month)
        days = ['一', '二', '三', '四', '五', '六', '日']
        for i, day in enumerate(days):
            ttk.Label(self.cal_frame, text=day).grid(row=0, column=i, padx=2, pady=2)

        for r, week in enumerate(month_days):
            for c, day in enumerate(week):
                if day != 0:
                    btn = ttk.Button(self.cal_frame, text=str(day), width=4, command=lambda d=day: self.select_date(d))
                    btn.grid(row=r + 1, column=c, padx=2, pady=2)

    def prev_month(self):
        self.current_date -= timedelta(days=self.current_date.day)
        self.update_calendar()

    def next_month(self):
        first_day, num_days = calendar.monthrange(self.current_date.year, self.current_date.month)
        self.current_date += timedelta(days=num_days - self.current_date.day + 1)
        self.update_calendar()

    def select_date(self, day):
        self.selected_date = date(self.current_date.year, self.current_date.month, day)
        self.entry_widget.delete(0, tk.END)
        self.entry_widget.insert(0, self.selected_date.strftime('%Y-%m-%d'))
        self.destroy()


class ManualEntryWindow:
    """补录数据窗口"""

    def __init__(self, parent, db_manager, target_date=None):
        self.win = tk.Toplevel(parent)
        self.win.withdraw()
        self.win.transient(parent)
        self.win.title("修改数据")

        parent.update_idletasks()
        parent_x, parent_y = parent.winfo_x(), parent.winfo_y()
        parent_width = parent.winfo_width()
        win_width, win_height = 400, 450
        new_x = parent_x + parent_width + 10
        new_y = parent_y
        self.win.geometry(f"{win_width}x{win_height}+{new_x}+{new_y}")

        self.db = db_manager
        self.dirty = False  # 标记数据是否被修改过

        frame = ttk.Frame(self.win, padding=15)
        frame.pack(expand=True, fill="both")

        date_frame = ttk.Frame(frame)
        date_frame.pack(fill='x', pady=5)
        ttk.Label(date_frame, text="选择日期:").pack(side='left', padx=(0, 10))
        self.date_entry = ttk.Entry(date_frame)
        display_date = target_date if target_date else date.today()
        self.date_entry.insert(0, display_date.strftime('%Y-%m-%d'))
        self.date_entry.pack(side='left', fill='x', expand=True)
        ttk.Button(date_frame, text="...", command=self.open_datepicker, width=3).pack(side='left', padx=(5, 0))
        ttk.Button(date_frame, text="加载", command=self.load_checkpoints).pack(side='left', padx=(10, 0))

        info_text = "说明：将按时间顺序两两配对（上班-下班）来计算总工时。"
        info_label = ttk.Label(frame, text=info_text, foreground="gray", wraplength=350, justify='left')
        info_label.pack(fill='x', pady=(10, 0))

        list_frame = ttk.Frame(frame)
        list_frame.pack(expand=True, fill='both', pady=10)
        self.checkpoints_listbox = tk.Listbox(list_frame)
        self.checkpoints_listbox.pack(side='left', expand=True, fill='both')
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.checkpoints_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.checkpoints_listbox.config(yscrollcommand=scrollbar.set)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill='x', pady=5)
        ttk.Button(btn_frame, text="添加", command=self.add_checkpoint).pack(side='left', expand=True, padx=2)
        ttk.Button(btn_frame, text="修改", command=self.modify_checkpoint).pack(side='left', expand=True, padx=2)
        ttk.Button(btn_frame, text="删除", command=self.delete_checkpoint).pack(side='left', expand=True, padx=2)

        self.load_checkpoints()
        self.win.deiconify()
        self.win.grab_set()
        parent.wait_window(self.win)

    def open_datepicker(self):
        """打开日期选择器"""
        DatePicker(self.win, self.date_entry)

    def load_checkpoints(self):
        """加载指定日期的时间点到列表"""
        self.checkpoints_listbox.delete(0, tk.END)
        try:
            target_date_str = self.date_entry.get()
            self.target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
            self.checkpoints = self.db.get_checkpoints_for_day(self.target_date)
            for cp in self.checkpoints:
                self.checkpoints_listbox.insert(tk.END, cp.strftime('%Y-%m-%d %H:%M:%S'))
        except ValueError:
            messagebox.showerror("错误", "日期格式不正确，应为 YYYY-MM-DD")

    def add_checkpoint(self):
        """添加一个新的时间点"""
        new_time_str = simpledialog.askstring("添加时间点", "请输入时间 (HH:MM:SS):", parent=self.win)
        if new_time_str:
            try:
                target_date_str = self.date_entry.get()
                full_datetime_str = f"{target_date_str} {new_time_str}"
                dt_obj = datetime.strptime(full_datetime_str, '%Y-%m-%d %H:%M:%S')
                if self.db.add_checkpoint(dt_obj):
                    self.load_checkpoints()
                    if self.target_date == date.today(): self.dirty = True
                else:
                    messagebox.showwarning("警告", "添加失败，该时间点可能已存在。")
            except ValueError:
                messagebox.showerror("错误", "时间格式不正确，应为 HH:MM:SS")

    def modify_checkpoint(self):
        """修改选中的时间点"""
        selected_indices = self.checkpoints_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("提示", "请先选择一个要修改的时间点。")
            return

        selected_index = selected_indices[0]
        old_checkpoint = self.checkpoints[selected_index]
        old_time_str = old_checkpoint.strftime('%H:%M:%S')

        new_time_str = simpledialog.askstring("修改时间点", "请输入新的时间 (HH:MM:SS):",
                                              initialvalue=old_time_str, parent=self.win)
        if new_time_str:
            try:
                target_date_str = self.date_entry.get()
                full_datetime_str = f"{target_date_str} {new_time_str}"
                new_checkpoint = datetime.strptime(full_datetime_str, '%Y-%m-%d %H:%M:%S')
                if self.db.delete_checkpoint(old_checkpoint):
                    if not self.db.add_checkpoint(new_checkpoint):
                        # If adding the new one fails, re-add the old one to avoid data loss
                        self.db.add_checkpoint(old_checkpoint)
                        messagebox.showwarning("警告", "修改失败，新的时间点可能与现有记录重复。")
                    else:
                        if self.target_date == date.today(): self.dirty = True
                    self.load_checkpoints()
                else:
                    messagebox.showerror("错误", "修改失败，无法删除旧记录。")
            except ValueError:
                messagebox.showerror("错误", "时间格式不正确，应为 HH:MM:SS")

    def delete_checkpoint(self):
        """删除选中的时间点"""
        selected_indices = self.checkpoints_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("提示", "请先选择一个要删除的时间点。")
            return

        selected_index = selected_indices[0]
        checkpoint_to_delete = self.checkpoints[selected_index]
        if messagebox.askyesno("确认删除", f"你确定要删除 {checkpoint_to_delete.strftime('%H:%M:%S')} 这个记录吗?"):
            if self.db.delete_checkpoint(checkpoint_to_delete):
                self.load_checkpoints()
                if self.target_date == date.today(): self.dirty = True
            else:
                messagebox.showerror("错误", "删除失败。")


class StatsWindow(tk.Toplevel):
    """统计数据窗口"""

    def __init__(self, parent, app, db_manager, formatter):
        super().__init__(parent)
        self.withdraw()
        self.transient(parent)
        self.title("工时统计")

        parent.update_idletasks()
        parent_x, parent_y = parent.winfo_x(), parent.winfo_y()
        parent_width = parent.winfo_width()
        win_width, win_height = 500, 400
        new_x = parent_x + parent_width + 10
        new_y = parent_y
        self.geometry(f"{win_width}x{win_height}+{new_x}+{new_y}")

        self.app = app
        self.db = db_manager
        self.formatter = formatter

        frame = ttk.Frame(self, padding=15)
        frame.pack(expand=True, fill="both")

        date_range_frame = ttk.Frame(frame)
        date_range_frame.pack(fill='x', pady=5)
        today = date.today()
        first_day_of_month = today.replace(day=1)
        ttk.Label(date_range_frame, text="从:").pack(side='left')
        self.start_date_entry = ttk.Entry(date_range_frame, width=12)
        self.start_date_entry.insert(0, first_day_of_month.strftime('%Y-%m-%d'))
        self.start_date_entry.pack(side='left', padx=5)
        ttk.Label(date_range_frame, text="到:").pack(side='left')
        self.end_date_entry = ttk.Entry(date_range_frame, width=12)
        self.end_date_entry.insert(0, today.strftime('%Y-%m-%d'))
        self.end_date_entry.pack(side='left', padx=5)
        ttk.Button(date_range_frame, text="生成报告", command=self.generate_report).pack(side='left', padx=10)

        tree_frame = ttk.Frame(frame)
        tree_frame.pack(expand=True, fill='both', pady=10)
        self.tree = ttk.Treeview(tree_frame, columns=('date', 'hours'), show='headings')
        self.tree.heading('date', text='日期')
        self.tree.heading('hours', text='总工时')
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        self.tree.pack(side='left', expand=True, fill='both')
        self.tree.bind("<Double-1>", self.on_date_double_click)
        self.tree.tag_configure('missing_punch', foreground='orange', font=('Helvetica', 9, 'italic'))
        self.tree.tag_configure('total', font=('Helvetica', 10, 'bold'))

        self.generate_report()
        self.deiconify()
        self.grab_set()

    def on_date_double_click(self, event):
        """处理在日期条目上的双击事件，跳转到修改窗口"""
        item_id = self.tree.identify_row(event.y)
        if not item_id: return
        item = self.tree.item(item_id)
        if not item['values']: return

        date_str = item['values'][0]
        try:
            # 尝试解析日期以确保它是一个有效的日期行（而不是总计行）
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            # 传入 self 作为父窗口，确保修改窗口显示在统计窗口之上
            self.app.open_manual_entry_window(parent_win=self, target_date=target_date)
            # 修改窗口关闭后，刷新统计报告以显示最新数据
            self.generate_report()
        except (ValueError, IndexError):
            # 如果点击的是总计行或标题行，则会解析失败，不做任何事
            pass

    def generate_report(self):
        """生成并显示统计报告"""
        for i in self.tree.get_children():
            self.tree.delete(i)
        last_item_id = None
        try:
            start_date = datetime.strptime(self.start_date_entry.get(), '%Y-%m-%d').date()
            end_date = datetime.strptime(self.end_date_entry.get(), '%Y-%m-%d').date()
        except ValueError:
            messagebox.showerror("错误", "日期格式不正确，应为 YYYY-MM-DD", parent=self)
            return
        if start_date > end_date:
            messagebox.showerror("错误", "开始日期不能晚于结束日期。", parent=self)
            return

        all_checkpoints = self.db.get_checkpoints_for_range(start_date, end_date)
        daily_data = {}
        for cp in all_checkpoints:
            day = cp.date()
            if day not in daily_data:
                daily_data[day] = []
            daily_data[day].append(cp)

        total_seconds_all_days = 0

        # 计算并显示每天的数据
        for day, checkpoints in sorted(daily_data.items()):
            total_seconds_day = self.calculate_worked_seconds_static(checkpoints)
            total_seconds_all_days += total_seconds_day
            display_hours = self.formatter(total_seconds_day)
            row_tags = ()

            # 如果打卡次数为奇数，则标记为漏打卡
            if len(checkpoints) % 2 != 0:
                display_hours += " (漏打卡)"
                row_tags = ('missing_punch',)
            last_item_id = self.tree.insert('', 'end', values=(day.strftime('%Y-%m-%d'), display_hours), tags=row_tags)

        # 显示总计
        last_item_id = self.tree.insert('', 'end', values=("--- 总计 ---", self.formatter(total_seconds_all_days)), tags=('total',))

        if last_item_id is not None:
            self.tree.update_idletasks()
            self.tree.see(last_item_id)

    @staticmethod
    def calculate_worked_seconds_static(checkpoints):
        """静态方法，用于计算秒数（统计窗口不需要知道当前状态）"""
        total_seconds = 0
        for i in range(0, len(checkpoints) - 1, 2):
            total_seconds += (checkpoints[i + 1] - checkpoints[i]).total_seconds()
        return total_seconds


if __name__ == "__main__":
    app_root = tk.Tk()
    config = ConfigManager()
    saved_db_path = config.load_db_path()

    try:
        db = DatabaseManager(db_path=saved_db_path)
        app = TimeTrackerApp(app_root, db, config)
        app_root.mainloop()
    except ConnectionError:
        # If the initial DB connection fails, the app will just close.
        # The error is already shown by the DatabaseManager.
        app_root.destroy()
