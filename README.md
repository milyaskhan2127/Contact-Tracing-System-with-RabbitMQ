👨‍💻 **Contact Tracing System with RabbitMQ**

🔍 **Project Overview**
I developed this **Contact Tracing System** as a sophisticated, client-oriented solution to track real-time interactions between individuals in a simulated environment. The system uses **RabbitMQ** as its messaging backbone, enabling a **distributed, responsive, and real-time tracking platform** with a professional GUI interface.

---

✨ **Key Features**

📍 **1. Real-Time Position Tracking**

* Simulates individuals moving randomly on a configurable grid
* Tracks exact positions and detects contact between people
* Visualizes movements and interactions on an interactive GUI

🧠 **2. Contact Tracing Engine**

* Maintains a full history of all contacts
* Retains up to 100 past contacts per individual (configurable)
* Query interface to view contact history

📡 **3. RabbitMQ Messaging System**

* Uses **fanout exchange** for broadcasting positions
* Uses **direct exchange** for querying specific individuals
* Implements a **request-response** pattern for contact queries
* Handles reconnection and error scenarios gracefully

🖥️ **4. Responsive GUI Interface**

* Dynamic grid that adjusts with window size
* Displays active individuals and real-time movement
* Tools for adding new simulated people
* Clean interface with contact querying and status indicators

🛠️ **5. Centralized Configuration**

* Uses a JSON file for:

  * Board/grid size
  * Update intervals
  * Logging level
  * RabbitMQ connection settings
* Easily customizable to meet different requirements

---

🧑‍💻 **Technical Implementation**

* **Language**: Python
* **GUI**: Tkinter
* **Messaging**: RabbitMQ (AMQP)
* **Threading**: For concurrent simulation, tracking, and UI updates
* **Data Serialization**: JSON

📦 **Architecture Components**

1. **Person Simulator** – Simulates and publishes movement to RabbitMQ
2. **Tracker** – Subscribes to positions, detects contacts, maintains history
3. **Query Tool** – Handles contact lookup queries via direct exchange
4. **GUI Interface** – Real-time visualization and user controls

---

🚀 **How to Run the System**

🔧 **Prerequisites**

* Docker
* Python 3.6+
* Install Python packages:

```bash
pip install pika tkinter ttkthemes
```

🐳 **1. Start RabbitMQ in Docker**

```bash
docker run -it --rm --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management
```

* Access Management UI at: [http://localhost:15672](http://localhost:15672)
* Login: `guest` / `guest`

⚙️ **2. (Optional) Configure the System**
Edit `config.json` for RabbitMQ host or system settings.

▶️ **3. Run the Application**

```bash
python contact_tracing.py
```

🧪 **Using the System**

* Launches with an empty grid
* Use "Add Person" to simulate movement
* Watch real-time movement and contact detection
* Query history for any individual

---

🏆 **Professional Impact**

This project was developed for a **client application** and showcases deep integration of RabbitMQ for **message-driven, real-time systems**. Key takeaways include:

* Real-world use of **fanout** and **direct exchanges**
* Clean **request-response workflow** over a message queue
* Practical **threaded architecture** supporting concurrent modules
* Modular and scalable design for potential deployment in:

  * Hospitals
  * Event venues
  * Public safety environments

It illustrates how message brokers like RabbitMQ can power distributed systems with high efficiency and flexibility. Watching the real-time GUI bring backend logic to life made this one of my most fulfilling professional experiences.

---

