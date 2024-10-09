import telebot
from telebot import types
import sqlite3

API_TOKEN = '7424841598:AAFVK9BDZHJz2ZJ5sj1GnCKoWtMHECb6ePM'


bot = telebot.TeleBot(API_TOKEN)
DB_FILE = 'queues.db'

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Создание таблицы очередей, если она не существует
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS queues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            queue_name TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            UNIQUE(chat_id, queue_name)
        )
    ''')

    # Проверка наличия столбца 'created_by' и добавление, если отсутствует
    cursor.execute("PRAGMA table_info(queues)")
    columns = [info[1] for info in cursor.fetchall()]
    if 'created_by' not in columns:
        cursor.execute('ALTER TABLE queues ADD COLUMN created_by INTEGER NOT NULL DEFAULT 0')

    # Создание таблицы участников очереди
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS queue_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            queue_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            username TEXT,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(queue_id, user_id),
            FOREIGN KEY(queue_id) REFERENCES queues(id) ON DELETE CASCADE
        )
    ''')

    conn.commit()
    conn.close()

def is_user_admin(chat_id, user_id):
    try:
        admins = bot.get_chat_administrators(chat_id)
        for admin in admins:
            if admin.user.id == user_id:
                return True
        return False
    except:
        return False

init_db()

@bot.message_handler(commands=['start'])
def handle_start(message):
    bot.reply_to(message, "Привет! Я бот для управления очередями.\n\nИспользуйте /create_queue для создания очереди.")

@bot.message_handler(commands=['create_queue'])
def handle_create_queue(message):
    msg = bot.reply_to(message, "Введите название очереди:")
    bot.register_next_step_handler(msg, receive_queue_name)

def receive_queue_name(message):
    queue_name = message.text.strip()
    chat_id = message.chat.id
    user_id = message.from_user.id

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        cursor.execute('''
            INSERT INTO queues (chat_id, queue_name, created_by)
            VALUES (?, ?, ?)
        ''', (chat_id, queue_name, user_id))
        conn.commit()
        queue_id = cursor.lastrowid

        # Отправка сообщения с пустым списком и кнопкой
        send_queue_message(chat_id, queue_id, queue_name)
        bot.send_message(chat_id, f"Очередь '{queue_name}' успешно создана!")
    except sqlite3.IntegrityError:
        bot.reply_to(message, "Очередь с таким названием уже существует.")
    finally:
        conn.close()

def send_queue_message(chat_id, queue_id, queue_name):
    # Формируем список участников (пока пустой)
    members = get_queue_members(queue_id)
    members_text = format_members_list(members)

    # Создаем inline-кнопки
    markup = types.InlineKeyboardMarkup()
    button_join = types.InlineKeyboardButton("✅ Встать в очередь", callback_data=f"join_{queue_id}")
    button_leave = types.InlineKeyboardButton("❌ Выйти из очереди", callback_data=f"leave_{queue_id}")
    markup.add(button_join, button_leave)

    # Отправляем сообщение
    bot.send_message(chat_id, f"📋 Очередь: {queue_name}\n\n📝 Список участников:\n{members_text}", reply_markup=markup)

def get_queue_members(queue_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT name, username FROM queue_members
        WHERE queue_id = ?
        ORDER BY joined_at ASC
    ''', (queue_id,))
    members = cursor.fetchall()
    conn.close()
    return members

def format_members_list(members):
    if not members:
        return "Очередь пока пуста."
    text = ""
    for idx, (name, username) in enumerate(members, start=1):
        if username:
            text += f"{idx}. {name} (@{username})\n"
        else:
            text += f"{idx}. {name}\n"
    return text

@bot.callback_query_handler(func=lambda call: call.data.startswith('join_') or call.data.startswith('leave_') or call.data.startswith('delete_'))
def handle_queue_actions(call):
    if call.data.startswith('join_'):
        handle_join_queue(call)
    elif call.data.startswith('leave_'):
        handle_leave_queue(call)
    elif call.data.startswith('delete_'):
        handle_delete_queue_callback(call)

def handle_join_queue(call):
    queue_id = int(call.data.split('_')[1])
    user_id = call.from_user.id
    name = call.from_user.full_name
    username = call.from_user.username
    chat_id = call.message.chat.id

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Проверяем, существует ли очередь
    cursor.execute('SELECT queue_name FROM queues WHERE id = ?', (queue_id,))
    result = cursor.fetchone()
    if not result:
        bot.answer_callback_query(call.id, "Очередь не найдена.")
        conn.close()
        return

    queue_name = result[0]

    # Проверяем, уже ли пользователь в очереди
    cursor.execute('SELECT * FROM queue_members WHERE queue_id = ? AND user_id = ?', (queue_id, user_id))
    if cursor.fetchone():
        bot.answer_callback_query(call.id, "Вы уже в очереди.")
        conn.close()
        return

    # Добавляем пользователя в очередь
    cursor.execute('''
        INSERT INTO queue_members (queue_id, user_id, name, username)
        VALUES (?, ?, ?, ?)
    ''', (queue_id, user_id, name, username))
    conn.commit()

    # Получаем обновленный список участников
    members = get_queue_members(queue_id)
    members_text = format_members_list(members)

    # Обновляем сообщение с очередью
    try:
        # Редактируем текст оригинального сообщения
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"📋 Очередь: {queue_name}\n\n📝 Список участников:\n{members_text}",
            reply_markup=call.message.reply_markup
        )
        bot.answer_callback_query(call.id, "Вы успешно встали в очередь.")
    except telebot.apihelper.ApiException:
        bot.answer_callback_query(call.id, "Не удалось обновить очередь.")

    conn.close()

def handle_leave_queue(call):
    queue_id = int(call.data.split('_')[1])
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Проверяем, существует ли очередь
    cursor.execute('SELECT queue_name FROM queues WHERE id = ?', (queue_id,))
    result = cursor.fetchone()
    if not result:
        bot.answer_callback_query(call.id, "Очередь не найдена.")
        conn.close()
        return

    queue_name = result[0]

    # Проверяем, находится ли пользователь в очереди
    cursor.execute('SELECT * FROM queue_members WHERE queue_id = ? AND user_id = ?', (queue_id, user_id))
    if not cursor.fetchone():
        bot.answer_callback_query(call.id, "Вы не в очереди.")
        conn.close()
        return

    # Удаляем пользователя из очереди
    cursor.execute('DELETE FROM queue_members WHERE queue_id = ? AND user_id = ?', (queue_id, user_id))
    conn.commit()

    # Получаем обновленный список участников
    members = get_queue_members(queue_id)
    members_text = format_members_list(members)

    # Обновляем сообщение с очередью
    try:
        # Редактируем текст оригинального сообщения
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"📋 Очередь: {queue_name}\n\n📝 Список участников:\n{members_text}",
            reply_markup=call.message.reply_markup
        )
        bot.answer_callback_query(call.id, "Вы успешно вышли из очереди.")
    except telebot.apihelper.ApiException:
        bot.answer_callback_query(call.id, "Не удалось обновить очередь.")

    conn.close()

def handle_delete_queue_callback(call):
    queue_id = int(call.data.split('_')[1])
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    # Проверяем, является ли пользователь администратором

    if not is_user_admin(chat_id, user_id):
        bot.answer_callback_query(call.id, "У вас нет прав для выполнения этой операции.")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Получаем информацию об очереди
    cursor.execute('SELECT queue_name FROM queues WHERE id = ?', (queue_id,))
    result = cursor.fetchone()

    if not result:
        bot.answer_callback_query(call.id, "Очередь не найдена.")
        conn.close()
        return

    queue_name = result[0]

    # Удаляем очередь и связанных участников
    cursor.execute('DELETE FROM queues WHERE id = ?', (queue_id,))
    cursor.execute('DELETE FROM queue_members WHERE queue_id = ?', (queue_id,))
    conn.commit()
    conn.close()

    # Удаляем сообщение с кнопками удаления очередей (опционально)
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except telebot.apihelper.ApiException:
        pass  # Игнорируем ошибку, если сообщение удалить не удалось

    bot.answer_callback_query(call.id, f"Очередь '{queue_name}' была удалена.")
    bot.send_message(chat_id, f"Очередь '{queue_name}' была удалена администрацией.")


@bot.message_handler(commands=['delete_queue'])
def handle_delete_queue(message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Проверяем, является ли пользователь администратором
    if not is_user_admin(chat_id, user_id):
        bot.reply_to(message, "У вас нет прав для выполнения этой команды.")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Получаем все очереди в текущем чате
    cursor.execute('SELECT id, queue_name FROM queues WHERE chat_id = ?', (chat_id,))
    queues = cursor.fetchall()
    conn.close()

    if not queues:
        bot.reply_to(message, "В этом чате нет созданных очередей.")
        return

    # Создаем сообщение со списком очередей и кнопками для удаления
    markup = types.InlineKeyboardMarkup()
    for queue in queues:
        queue_id, queue_name = queue
        button = types.InlineKeyboardButton(f"❌ Удалить '{queue_name}'", callback_data=f"delete_{queue_id}")
        markup.add(button)

    bot.send_message(chat_id, "Выберите очередь для удаления:", reply_markup=markup)


# Запуск бота
bot.polling(none_stop=True)

