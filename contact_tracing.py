import pika
import json
import random
import threading
import time
from collections import defaultdict, deque
from tkinter import (
    Tk, Canvas, Text, Scrollbar, Frame, Label, Entry, Button, 
    StringVar, SUNKEN, BOTH, LEFT, RIGHT, TOP, BOTTOM, X, Y, END, WORD
)
from tkinter import messagebox
from tkinter import ttk 
import queue
from datetime import datetime
import logging
from tracker_config import config

# Configuration from config file
BOARD_SIZE = config.get("board_size", 10)
UPDATE_INTERVAL = config.get("update_interval", 100)
MAX_HISTORY = config.get("max_history", 100)
RABBITMQ_HOST = config.get("rabbitmq_host", "localhost")

logger = logging.getLogger(__name__)

def setup_rabbitmq_connection(host=RABBITMQ_HOST):
    # Helper function to create a RabbitMQ connection with standardized exchange declaration
    connection = pika.BlockingConnection(pika.ConnectionParameters(host=host))
    channel = connection.channel()
    
    try:
        # Position exchange (fanout - broadcasts to all)
        channel.exchange_declare(
            exchange='position',
            exchange_type='fanout',
            durable=True
        )
        
        # Query exchange (direct - for specific queries)
        channel.exchange_declare(
            exchange='query',
            exchange_type='direct',
            durable=True
        )
        
        # Response exchange (direct - for query responses)
        channel.exchange_declare(
            exchange='query_response',
            exchange_type='direct',
            durable=True
        )
    except pika.exceptions.ChannelClosedByBroker as e:
        if 'PRECONDITION_FAILED' in str(e):
            logger.info("Exchange already exists with different parameters. Using existing exchange.")
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=host))
            channel = connection.channel()
        else:
            logger.error(f"RabbitMQ channel error: {e}")
            raise
    
    return connection, channel

class Tracker:
    def __init__(self, rabbitmq_host=RABBITMQ_HOST):
        self.positions = {}
        self.contact_history = defaultdict(deque)
        self.max_history = MAX_HISTORY
        
        # RabbitMQ setup
        self.setup_rabbitmq(rabbitmq_host)
        
    def setup_rabbitmq(self, host):
        try:
            self.rabbit_conn, self.rabbit_channel = setup_rabbitmq_connection(host)
            
            # Position queue
            self.position_queue = self.rabbit_channel.queue_declare(queue='', exclusive=True).method.queue
            self.rabbit_channel.queue_bind(exchange='position', queue=self.position_queue)
            self.rabbit_channel.basic_consume(
                queue=self.position_queue,
                on_message_callback=self.handle_position_update,
                auto_ack=True
            )
            
            # Query queue
            self.query_queue = self.rabbit_channel.queue_declare(queue='', exclusive=True).method.queue
            self.rabbit_channel.queue_bind(exchange='query', queue=self.query_queue, routing_key='tracker_query')
            self.rabbit_channel.basic_consume(
                queue=self.query_queue,
                on_message_callback=self.handle_query,
                auto_ack=True
            )
            
            logger.info("RabbitMQ connection established for Tracker")
        except Exception as e:
            logger.error(f"Failed to setup RabbitMQ: {e}")
            raise
        
    def handle_position_update(self, ch, method, properties, body):
        try:
            data = json.loads(body)
            person_id = data['person_id']
            x, y = data['position']
            
            old_pos = self.positions.get(person_id)
            self.positions[person_id] = (x, y)
            
            if old_pos != (x, y):
                self.check_contacts(person_id, x, y)
            logger.debug(f"Updated position for {person_id}: {x},{y}")
        except Exception as e:
            logger.error(f"Error processing position update: {e}")

    def check_contacts(self, person_id, x, y):
        """Check if the current position creates contacts with others"""
        contacts = []
        for other_id, other_pos in self.positions.items():
            if other_id != person_id and other_pos == (x, y):
                contact_info = {
                    'person': other_id,
                    'position': (x, y),
                    'time': time.time()
                }
                contacts.append(contact_info)
                logger.info(f"CONTACT DETECTED: {person_id} and {other_id} at {x},{y} at {time.time()}")
        
        # Update contact history for all detected contacts
        for contact in contacts:
            self.update_contact_history(person_id, contact)
            # Also update the other person's contact history
            reverse_contact = {
                'person': person_id,
                'position': (x, y),
                'time': time.time()
            }
            self.update_contact_history(contact['person'], reverse_contact)

    def handle_query(self, ch, method, properties, body):
        try:
            person_id = body.decode()
            logger.info(f"Processing query for {person_id} (reply_to: {properties.reply_to})")
            
            contacts = []
            for contact in self.contact_history.get(person_id, []):
                contacts.append({
                    'person': contact['person'],
                    'position': contact['position'],
                    'time': contact['time']
                })
            
            response = json.dumps({
                'person_id': person_id,
                'contacts': contacts,
                'timestamp': time.time()
            })
            
            # Log the routing details
            logger.info(f"Sending to exchange 'query_response' with routing_key '{properties.reply_to}'")
            
            self.rabbit_channel.basic_publish(
                exchange='query_response',
                routing_key=properties.reply_to,  # Use the callback queue name as routing key
                body=response,
                properties=pika.BasicProperties(
                    correlation_id=properties.correlation_id,
                    content_type='application/json'
                )
            )
            logger.info(f"Sent response for {person_id} with {len(contacts)} contacts")
        except Exception as e:
            logger.error(f"Error processing query: {e}")

    def update_contact_history(self, person_id, contact_info):
        if len(self.contact_history[person_id]) >= self.max_history:
            self.contact_history[person_id].popleft()
        self.contact_history[person_id].append(contact_info)
        logger.debug(f"Updated contact history for {person_id}")
        
    def run(self):
        logger.info("Tracker started. Listening for position updates and queries...")
        try:
            self.rabbit_channel.start_consuming()
        except KeyboardInterrupt:
            logger.info("Shutting down tracker...")
            self.rabbit_channel.stop_consuming()
        except Exception as e:
            logger.error(f"Tracker error: {e}")
        finally:
            self.rabbit_conn.close()

class PersonSimulator:
    def __init__(self, person_id, speed, rabbitmq_host=RABBITMQ_HOST, board_size=BOARD_SIZE):
        self.person_id = person_id
        self.speed = speed
        self.board_size = board_size
        self.position = (random.randint(0, board_size-1), random.randint(0, board_size-1))
        self.setup_rabbitmq(rabbitmq_host)
        self.publish_position()
        
    def setup_rabbitmq(self, host):
        try:
            self.rabbit_conn, self.rabbit_channel = setup_rabbitmq_connection(host)
            logger.debug(f"RabbitMQ setup for {self.person_id}")
        except Exception as e:
            logger.error(f"Failed to setup RabbitMQ for {self.person_id}: {e}")
            raise
        
    def publish_position(self):
        try:
            message = json.dumps({
                'person_id': self.person_id,
                'position': self.position,
                'speed': self.speed,
                'timestamp': time.time()
            })
            self.rabbit_channel.basic_publish(
                exchange='position',
                routing_key='',
                body=message,
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type='application/json'
                )
            )
            logger.debug(f"{self.person_id} published position: {self.position}")
        except Exception as e:
            logger.error(f"Failed to publish position for {self.person_id}: {e}")
        
    def move_randomly(self):
        directions = [(0,1), (1,0), (0,-1), (-1,0), (1,1), (1,-1), (-1,1), (-1,-1)]
        dx, dy = random.choice(directions)
        new_x = max(0, min(self.board_size-1, self.position[0] + dx))
        new_y = max(0, min(self.board_size-1, self.position[1] + dy))
        self.position = (new_x, new_y)
        self.publish_position()
        logger.debug(f"{self.person_id} moved to {self.position}")
        
    def run(self):
        logger.info(f"Person {self.person_id} started at {self.position}")
        try:
            while True:
                time.sleep(1.0 / self.speed)
                self.move_randomly()
        except KeyboardInterrupt:
            logger.info(f"Stopping {self.person_id}")
        except Exception as e:
            logger.error(f"Error in {self.person_id} simulator: {e}")
        finally:
            self.rabbit_conn.close()

class QueryTool:
    def __init__(self, rabbitmq_host=RABBITMQ_HOST):
        try:
            self.rabbit_conn = pika.BlockingConnection(
                pika.ConnectionParameters(host=rabbitmq_host))
            self.rabbit_channel = self.rabbit_conn.channel()
            
            # Setup response queue with explicit binding
            result = self.rabbit_channel.queue_declare(queue='', exclusive=True)
            self.callback_queue = result.method.queue
            
            # Bind the queue to the response exchange with the queue name as routing key
            self.rabbit_channel.queue_bind(
                exchange='query_response',
                queue=self.callback_queue,
                routing_key=self.callback_queue
            )
            
            self.response = None
            self.corr_id = None
            logger.info(f"Query tool connected to RabbitMQ. Response queue: {self.callback_queue}")
        except Exception as e:
            logger.error(f"Failed to setup QueryTool: {e}")
            raise
        
    def on_response(self, ch, method, props, body):
        if self.corr_id == props.correlation_id:
            try:
                self.response = json.loads(body)
                logger.info(f"Received valid response for {props.correlation_id}")
            except json.JSONDecodeError:
                logger.error("Failed to decode response JSON")
        
    def query_contacts(self, person_id):
        self.response = None
        self.corr_id = str(time.time())
        
        try:
            # Start consuming before sending the request
            self.rabbit_channel.basic_consume(
                queue=self.callback_queue,
                on_message_callback=self.on_response,
                auto_ack=True
            )
            
            logger.info(f"Sending query for {person_id} (corr_id: {self.corr_id})")
            self.rabbit_channel.basic_publish(
                exchange='query',
                routing_key='tracker_query',
                properties=pika.BasicProperties(
                    reply_to=self.callback_queue,
                    correlation_id=self.corr_id,
                    content_type='text/plain'
                ),
                body=person_id
            )
            
            # Process events with a timeout
            start_time = time.time()
            while not self.response and (time.time() - start_time) < 5:
                self.rabbit_conn.process_data_events()
                time.sleep(0.1)
            
            if self.response:
                logger.info(f"Got valid response for {person_id}")
                return self.response
            else:
                logger.warning(f"No response received for {person_id}")
                return None
                
        except Exception as e:
            logger.error(f"Query failed for {person_id}: {e}")
            return None
        finally:
            # Cancel consumer to clean up
            self.rabbit_channel.basic_cancel(self.rabbit_channel.consumer_tags[0])



class ContactTracingGUI:
    def __init__(self, root, board_size=10):
        self.root = root
        self.board_size = board_size
        self.cell_size = 50
        self.canvas_width = self.board_size * self.cell_size
        self.canvas_height = self.board_size * self.cell_size
        self.people_data = {}
        self.position_queue = queue.Queue()
        
        # Color scheme
        self.colors = {
            'bg': '#f5f5f5',
            'panel_bg': '#ffffff',
            'accent': '#4a6fa5',
            'accent_light': '#6a8fc5',
            'text': '#333333',
            'highlight': '#ff6b6b',
            'grid': '#e0e0e0',
            'status_bg': '#e9e9e9'
        }
        
        self.setup_gui()
        self.start_middleware_connections()
        self.update_gui()
        self.setup_responsive_layout()
        self.last_cell_size = self.cell_size

    def setup_responsive_layout(self):
        """Set up bindings for window resize events"""
        self.root.bind("<Configure>", self.on_window_resize)
        self.last_window_width = self.root.winfo_width()
        self.last_window_height = self.root.winfo_height()

    def on_window_resize(self, event):
        """Handle window resize events"""
        if event.widget == self.root:
            new_width = event.width
            new_height = event.height
            
            # Only adjust if the change is significant
            if (abs(new_width - self.last_window_width) > 50 or 
                abs(new_height - self.last_window_height) > 50):
                self.adjust_layout_for_size(new_width, new_height)
                self.last_window_width = new_width
                self.last_window_height = new_height

    def adjust_layout_for_size(self, width, height):
        """Adjust layout based on current window size"""
        # Calculate available space for the canvas
        left_panel_width = width - 400
        max_cell_size = min(left_panel_width // self.board_size, 
                           (height - 100) // self.board_size)
        
        # Set cell size within reasonable bounds
        new_cell_size = max(20, min(50, max_cell_size))
        
        # Only redraw if cell size actually changed
        if new_cell_size != self.cell_size:
            self.cell_size = new_cell_size
            self.canvas_width = self.board_size * self.cell_size
            self.canvas_height = self.board_size * self.cell_size
            
            # Update canvas dimensions
            self.canvas.config(width=self.canvas_width, height=self.canvas_height)
            
            # Clear and redraw everything
            self.canvas.delete("all")
            self.draw_grid()
            self.draw_people() 
            
            # Update scroll region
            self.canvas.config(scrollregion=self.canvas.bbox("all"))

    def setup_gui(self):
        self.root.title("Contact Tracing System")
        self.root.geometry("1200x800")
        self.root.minsize(800, 600) 
        self.root.configure(bg=self.colors['bg'])
        
        # Main container
        self.main_frame = Frame(self.root, bg=self.colors['bg'])
        self.main_frame.pack(fill=BOTH, expand=True, padx=5, pady=5)
        
        # Left panel - Board
        self.left_panel = Frame(self.main_frame, bg=self.colors['bg'])
        self.left_panel.pack(side=LEFT, fill=BOTH, expand=True, padx=5, pady=5)
        
        # Board frame
        board_frame = Frame(self.left_panel, bg=self.colors['panel_bg'], bd=2, relief='groove')
        board_frame.pack(fill=BOTH, expand=True, pady=(0, 5))
        
        Label(board_frame, text="Contact Tracing Board", bg=self.colors['panel_bg'], 
              fg=self.colors['accent'], font=('Arial', 12, 'bold')).pack(pady=5)
        
        # Board canvas with scrollbars
        canvas_container = Frame(board_frame, bg=self.colors['panel_bg'])
        canvas_container.pack(fill=BOTH, expand=True, padx=5, pady=5)
        
        # Add scrollbars
        canvas_vscroll = Scrollbar(canvas_container, orient='vertical')
        canvas_hscroll = Scrollbar(canvas_container, orient='horizontal')
        
        self.canvas = Canvas(canvas_container, 
                           width=self.canvas_width, 
                           height=self.canvas_height,
                           bg='white',
                           yscrollcommand=canvas_vscroll.set,
                           xscrollcommand=canvas_hscroll.set,
                           highlightthickness=0)
        
        canvas_vscroll.config(command=self.canvas.yview)
        canvas_hscroll.config(command=self.canvas.xview)
        
        # Grid layout for canvas and scrollbars
        self.canvas.grid(row=0, column=0, sticky='nsew')
        canvas_vscroll.grid(row=0, column=1, sticky='ns')
        canvas_hscroll.grid(row=1, column=0, sticky='ew')
        
        canvas_container.grid_rowconfigure(0, weight=1)
        canvas_container.grid_columnconfigure(0, weight=1)
        
        self.draw_grid()
        
        # Right panel - All controls and info
        self.right_panel = Frame(self.main_frame, bg=self.colors['bg'], width=350)
        self.right_panel.pack(side=RIGHT, fill=Y, expand=False, padx=5, pady=5)
        
        # Active people frame (top of right panel)
        active_frame = Frame(self.right_panel, bg=self.colors['panel_bg'], bd=2, relief='groove')
        active_frame.pack(fill=X, pady=(0, 10))
        
        Label(active_frame, text="Active People", bg=self.colors['panel_bg'], 
              fg=self.colors['accent'], font=('Arial', 12, 'bold')).pack(pady=5)
        
        # Treeview for active people with scrollbar
        tree_frame = Frame(active_frame, bg=self.colors['panel_bg'])
        tree_frame.pack(fill=BOTH, expand=True, padx=5, pady=5)
        
        self.people_tree = ttk.Treeview(
            tree_frame,
            columns=("person_id", "position", "speed"),
            show="headings",
            height=8  # Reduced height to make space for other controls
        )
        self.people_tree.heading("person_id", text="Person ID")
        self.people_tree.heading("position", text="Position")
        self.people_tree.heading("speed", text="Speed")
        self.people_tree.column("person_id", width=100, anchor='center')
        self.people_tree.column("position", width=80, anchor='center')
        self.people_tree.column("speed", width=60, anchor='center')
        
        tree_scroll = ttk.Scrollbar(tree_frame, orient='vertical', command=self.people_tree.yview)
        self.people_tree.configure(yscrollcommand=tree_scroll.set)
        
        self.people_tree.pack(side=LEFT, fill=BOTH, expand=True)
        tree_scroll.pack(side=RIGHT, fill=Y)
        
        # Add person frame (middle of right panel)
        add_person_frame = Frame(self.right_panel, bg=self.colors['panel_bg'], bd=2, relief='groove')
        add_person_frame.pack(fill=X, pady=(0, 10))
        
        Label(add_person_frame, text="Add New Person", bg=self.colors['panel_bg'], 
              fg=self.colors['accent'], font=('Arial', 12, 'bold')).pack(pady=5)
        
        add_content = Frame(add_person_frame, bg=self.colors['panel_bg'])
        add_content.pack(padx=10, pady=5)
        
        Label(add_content, text="Person ID:", bg=self.colors['panel_bg'], 
              fg=self.colors['text']).grid(row=0, column=0, sticky='w', pady=2)
        
        self.person_id_entry = Entry(add_content, width=20, font=('Arial', 10), 
                                    bd=1, relief='solid')
        self.person_id_entry.grid(row=0, column=1, pady=2, padx=5)
        
        Label(add_content, text="Speed (moves/sec):", bg=self.colors['panel_bg'], 
              fg=self.colors['text']).grid(row=1, column=0, sticky='w', pady=2)
        
        self.speed_entry = Entry(add_content, width=20, font=('Arial', 10), 
                               bd=1, relief='solid')
        self.speed_entry.grid(row=1, column=1, pady=2, padx=5)
        self.speed_entry.insert(0, "1")
        
        self.add_person_btn = Button(add_content, text="Add Person", 
                                    bg=self.colors['accent'], fg='white',
                                    activebackground=self.colors['accent_light'],
                                    font=('Arial', 10), bd=0,
                                    command=self.add_person)
        self.add_person_btn.grid(row=2, column=0, columnspan=2, pady=5, sticky='ew')
        
        # Query frame (bottom of right panel)
        query_frame = Frame(self.right_panel, bg=self.colors['panel_bg'], bd=2, relief='groove')
        query_frame.pack(fill=BOTH, expand=True)
        
        Label(query_frame, text="Contact Query", bg=self.colors['panel_bg'], 
              fg=self.colors['accent'], font=('Arial', 12, 'bold')).pack(pady=5)
        
        # Center the query content frame
        query_content = Frame(query_frame, bg=self.colors['panel_bg'])
        query_content.pack(padx=10, pady=5)

        # Configure grid columns for centering
        query_content.grid_columnconfigure(0, weight=1)
        query_content.grid_columnconfigure(1, weight=1)

        Label(query_content, text="Person ID:", bg=self.colors['panel_bg'], 
              fg=self.colors['text']).grid(row=0, column=0, sticky='e', pady=2, padx=(0,5))

        self.query_entry = Entry(query_content, width=20, font=('Arial', 10), 
                               bd=1, relief='solid')
        self.query_entry.grid(row=0, column=1, pady=2, padx=(5,0))

        self.query_btn = Button(query_content, text="Query Contacts", 
                              bg=self.colors['accent'], fg='white',
                              activebackground=self.colors['accent_light'],
                              font=('Arial', 10), bd=0,
                              command=self.query_contacts)
        self.query_btn.grid(row=1, column=0, columnspan=2, pady=5, sticky='ew')
        
        # Results frame (below query in right panel)
        results_frame = Frame(self.right_panel, bg=self.colors['panel_bg'], bd=2, relief='groove')
        results_frame.pack(fill=BOTH, expand=True, pady=(10, 0))
        
        Label(results_frame, text="Query Results", bg=self.colors['panel_bg'], 
              fg=self.colors['accent'], font=('Arial', 12, 'bold')).pack(pady=5)
        
        # Text widget with scrollbar
        text_frame = Frame(results_frame, bg=self.colors['panel_bg'])
        text_frame.pack(fill=BOTH, expand=True, padx=10, pady=5)
        
        self.results_text = Text(text_frame, wrap=WORD, font=('Arial', 10), 
                               bg='white', fg=self.colors['text'], 
                               padx=5, pady=5, bd=1, relief='solid',
                               height=8) 
        scrollbar = Scrollbar(text_frame, command=self.results_text.yview)
        self.results_text.configure(yscrollcommand=scrollbar.set)
        
        self.results_text.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)
        
        # Status bar at bottom
        self.status_var = StringVar()
        self.status_var.set("Ready")
        status_bar = Label(self.main_frame, textvariable=self.status_var, 
                         bg=self.colors['status_bg'], fg=self.colors['text'], 
                         font=('Arial', 10), bd=1, relief=SUNKEN, anchor='w')
        status_bar.pack(side=BOTTOM, fill=X, padx=5, pady=(0, 5))
    
    def draw_grid(self):
        """Draw the grid lines on the canvas with proper spacing"""
        self.canvas.delete("grid") 
        
        # Draw vertical lines
        for i in range(self.board_size + 1):
            x = i * self.cell_size
            self.canvas.create_line(x, 0, x, self.canvas_height, 
                                  fill=self.colors['grid'], tags="grid")
        
        # Draw horizontal lines
        for i in range(self.board_size + 1):
            y = i * self.cell_size
            self.canvas.create_line(0, y, self.canvas_width, y, 
                                  fill=self.colors['grid'], tags="grid")

    def draw_people(self):
        """Draw people on the canvas with proper scaling"""
        self.canvas.delete("people")
        self.canvas.delete("meeting")
        
        # Calculate visual elements size based on current cell size
        person_radius = self.cell_size // 3
        meeting_radius = self.cell_size // 2
        
        # First pass: Draw all people
        for person_id, data in self.people_data.items():
            x, y = data['position']
            canvas_x = x * self.cell_size + self.cell_size // 2
            canvas_y = y * self.cell_size + self.cell_size // 2
            color = f'#{hash(person_id) % 0xffffff:06x}'
            
            # Draw person
            self.canvas.create_oval(
                canvas_x - person_radius, canvas_y - person_radius,
                canvas_x + person_radius, canvas_y + person_radius,
                fill=color, tags="people", outline='black'
            )
            
            # Draw initial
            self.canvas.create_text(
                canvas_x, canvas_y,
                text=person_id[0].upper(),
                fill='white',
                tags="people",
                font=('Arial', max(8, self.cell_size//5), 'bold')
            )
        
        # Second pass: Draw meeting indicators
        meeting_spots = defaultdict(list)
        for person_id, data in self.people_data.items():
            pos = data['position']
            meeting_spots[pos].append(person_id)
        
        for pos, people in meeting_spots.items():
            if len(people) > 1:
                x, y = pos
                canvas_x = x * self.cell_size + self.cell_size // 2
                canvas_y = y * self.cell_size + self.cell_size // 2
                
                # Draw meeting circle
                self.canvas.create_oval(
                    canvas_x - meeting_radius, canvas_y - meeting_radius,
                    canvas_x + meeting_radius, canvas_y + meeting_radius,
                    outline='red', width=2, tags="meeting",
                    dash=(5, 3)
                )
                
                # Draw meeting text
                self.canvas.create_text(
                    canvas_x, canvas_y - meeting_radius - 5,
                    text=f"{len(people)} people",
                    fill='red',
                    tags="meeting",
                    font=('Arial', max(6, self.cell_size//6), 'bold') 
                )
            
    def add_person(self):
        person_id = self.person_id_entry.get().strip()
        try:
            speed = float(self.speed_entry.get())
            if speed <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Speed must be a positive number")
            return
            
        if not person_id:
            messagebox.showerror("Error", "Person ID cannot be empty")
            return
            
        if person_id in self.people_data:
            messagebox.showerror("Error", f"Person '{person_id}' already exists")
            return
            
        # Add to active people tree
        self.people_tree.insert('', 'end', values=(person_id, "(1,1)", f"{speed:.1f}"))
        
        threading.Thread(
            target=lambda: PersonSimulator(person_id, speed, board_size=self.board_size).run(),
            daemon=True
        ).start()
        
        self.status_var.set(f"Added person {person_id} with speed {speed:.1f} moves/sec")
        self.person_id_entry.delete(0, END)
        logger.info(f"Added new person: {person_id} with speed {speed}")
        
    def query_contacts(self):
        person_id = self.query_entry.get().strip()
        if not person_id:
            messagebox.showerror("Error", "Please enter a person ID to query")
            return
        
        # Check if person exists in active people
        person_exists = False
        for item in self.people_tree.get_children():
            if self.people_tree.item(item, 'values')[0] == person_id:
                person_exists = True
                break
        
        if not person_exists:
            self.results_text.delete(1.0, END)
            self.results_text.insert(END, f"No active person found with ID: {person_id}")
            logger.warning(f"Query attempted for non-existent person: {person_id}")
            return
        
        query_tool = QueryTool()
        result = query_tool.query_contacts(person_id)
        
        self.results_text.delete(1.0, END)
        if result:
            contacts = result.get('contacts', [])
            self.results_text.insert(END, f"Contact history for {person_id}:\n\n")
            
            if not contacts:
                self.results_text.insert(END, "No contacts recorded")
            else:
                for contact in contacts:
                    contact_time = datetime.fromtimestamp(contact['time']).strftime('%Y-%m-%d %H:%M:%S')
                    self.results_text.insert(END, 
                        f"• Met {contact['person']} at position {contact['position']} "
                        f"on {contact_time}\n"
                    )
            logger.info(f"Displayed contact history for {person_id}")
        else:
            self.results_text.insert(END, "No response received from tracker")
            logger.warning(f"No response received for query about {person_id}")
            
    def start_middleware_connections(self):
        # Start tracker in background
        threading.Thread(
            target=lambda: Tracker().run(),
            daemon=True
        ).start()
        
        # Start position listener
        threading.Thread(
            target=self.listen_to_positions,
            daemon=True
        ).start()
        logger.info("Started middleware connections")
        
    def listen_to_positions(self):
        connection, channel = setup_rabbitmq_connection()
        result = channel.queue_declare(queue='', exclusive=True)
        queue_name = result.method.queue
        channel.queue_bind(exchange='position', queue=queue_name)
        
        def callback(ch, method, properties, body):
            try:
                data = json.loads(body)
                self.position_queue.put(data)
                logger.debug(f"Received position update in GUI: {data['person_id']}")
            except Exception as e:
                logger.error(f"Error processing position update in GUI: {e}")
                
        channel.basic_consume(
            queue=queue_name,
            on_message_callback=callback,
            auto_ack=True
        )
        
        channel.start_consuming()
        
    def update_gui(self):
        # Process all queued position updates
        while not self.position_queue.empty():
            data = self.position_queue.get()
            person_id = data['person_id']
            position = tuple(data['position'])
            speed = data.get('speed', 1.0)
            
            # Update people data
            self.people_data[person_id] = {
                'position': position,
                'speed': speed,
                'last_update': time.time()
            }
            
            # Update active people treeview
            found = False
            for item in self.people_tree.get_children():
                if self.people_tree.item(item, 'values')[0] == person_id:
                    # Convert (x, y) from 0-based to 1-based for display
                    display_position = f"({position[0]+1},{position[1]+1})"
                    self.people_tree.item(item, values=(person_id, display_position, f"{speed:.1f}"))
                    found = True
                    break
                    
            if not found:
                # Convert (x, y) from 0-based to 1-based for display
                display_position = f"({position[0]+1},{position[1]+1})"
                self.people_tree.insert('', 'end', values=(person_id, display_position, f"{speed:.1f}"))
        
        # Remove inactive people (not updated in last 5 seconds)
        current_time = time.time()
        inactive = []
        for person_id, data in self.people_data.items():
            if current_time - data['last_update'] > 5:
                inactive.append(person_id)
                
        for person_id in inactive:
            self.people_data.pop(person_id, None)
            for item in self.people_tree.get_children():
                if self.people_tree.item(item, 'values')[0] == person_id:
                    self.people_tree.delete(item)
                    break
                    logger.info(f"Removed inactive person: {person_id}")
        
        self.canvas.delete("meeting")
        self.draw_people()
        self.root.after(UPDATE_INTERVAL, self.update_gui)

def main():
    root = Tk()
    try:
        # Set theme (requires ttkthemes package - optional)
        from ttkthemes import ThemedStyle
        style = ThemedStyle(root)
        style.set_theme("arc")
        logger.debug("Applied arc theme")
    except ImportError as e:
        logger.debug(f"Couldn't load ttkthemes: {e}")
        pass 
        
    gui = ContactTracingGUI(root)
    logger.info("GUI application started")
    root.mainloop()

if __name__ == "__main__":
    main()