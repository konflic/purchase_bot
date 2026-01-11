import logging
import os
import re
from pathlib import Path
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,  # Added for type hinting in post_init
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ConversationHandler,
)

try:
    from config import TOKEN as TELEGRAM_BOT_TOKEN
except ImportError:
    TELEGRAM_BOT_TOKEN = None

USER_DATA_BASE_DIR = Path("user_purchase_lists")
CURRENT_LIST_KEY = "current_list_name"
LIST_TO_DELETE_KEY = "list_to_delete_temp_name"
DEFAULT_TIMEOUT = 30

(
    AWAITING_ITEM_FOR_ADD,
    AWAITING_LISTNAME_FOR_CREATE,
    AWAITING_LISTNAME_FOR_DELETE,
    AWAITING_CONFIRM_DELETE,
) = range(4)


logger = logging.getLogger("bot")


class Commands:
    CREATE_LIST = "/create_list"
    SHOW_LISTS = "/show_lists"
    SET_ACTIVE_LIST = "/select_list"
    DELETE_LIST = "/delete_list"
    ADD_ITEM = "/add_item"
    SHOW_ITEMS = "/list_items"
    REMOVE_ITEM = "/remove_item"
    HELP = "/help"
    CANCEL = "/cancel"


def sanitize_filename(name: str) -> str:
    name = str(name)
    name = re.sub(r"[^\w\s-]", "_", name)
    name = name.strip(" _.-")
    name = name.replace(" ", "_")
    if not name:
        return "untitled_list"
    return name


def get_user_dir(user_id: int) -> Path:
    user_dir_path = USER_DATA_BASE_DIR / str(user_id)
    user_dir_path.mkdir(parents=True, exist_ok=True)
    return user_dir_path


def get_user_list_path(user_id: int, list_name: str) -> Path:
    sanitized_list_name = sanitize_filename(list_name)
    return get_user_dir(user_id) / f"{sanitized_list_name}.txt"


def get_all_list_names(user_id: int) -> list[str]:
    user_dir = get_user_dir(user_id)
    all_lists = sorted([p.stem for p in user_dir.glob("*.txt") if p.is_file()])
    # Ensure 'default' is always first if it exists
    if "default" in all_lists:
        all_lists.remove("default")
        all_lists.insert(0, "default")
    return all_lists


def read_list(user_id: int, list_name: str) -> list[str]:
    list_path = get_user_list_path(user_id, list_name)
    if not list_path.exists():
        return []
    try:
        with open(list_path, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except Exception:
        return []


def write_list(user_id: int, list_name: str, items: list[str]):
    list_path = get_user_list_path(user_id, list_name)
    try:
        list_path.parent.mkdir(parents=True, exist_ok=True)
        with open(list_path, "w", encoding="utf-8") as f:
            for item in items:
                f.write(f"{item}\n")
    except Exception:
        pass


def get_standard_keyboard() -> InlineKeyboardMarkup:
    """Create standard inline keyboard with common actions"""
    keyboard = [
        [
            InlineKeyboardButton("📋 Показать списки", callback_data="show_lists"),
            InlineKeyboardButton("📝 Показать элементы", callback_data="show_items"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


async def ensure_list_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str | None:
    current_list_name = context.user_data.get(CURRENT_LIST_KEY)
    user = update.effective_user
    if not user or not update.message:
        return None

    if not current_list_name:
        await update.message.reply_text(
            "Не выбран список!\n"
            f"{Commands.CREATE_LIST} - Создать новый список\n"
            f"{Commands.SET_ACTIVE_LIST} - Выбрать ранее созданный список\n"
            f"{Commands.SHOW_LISTS} - Показать списки пользователя"
        )
        return None
    if not get_user_list_path(user.id, current_list_name).exists():
        await update.message.reply_text(
            f"Выбранный список '{current_list_name}' больше не существует.\n"
            f"Выберите {Commands.SET_ACTIVE_LIST} другой список или {Commands.CREATE_LIST} создайте новый."
        )
        if CURRENT_LIST_KEY in context.user_data:
            del context.user_data[CURRENT_LIST_KEY]
        return None
    return current_list_name


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Операция отменена")
    context.user_data.pop(LIST_TO_DELETE_KEY, None)
    # Potentially clear other conversation-specific keys if you add more
    return ConversationHandler.END


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.message:
        return

    get_user_dir(user.id)

    write_list(user.id, "default", [])

    all_lists = get_all_list_names(user.id)
    # Auto-select default list if no list is selected
    if not context.user_data.get(CURRENT_LIST_KEY):
        if "default" in all_lists:
            context.user_data[CURRENT_LIST_KEY] = "default"
            await update.message.reply_text(f"Автоматически выбран список: 'default'.")
        elif len(all_lists) == 1:
            context.user_data[CURRENT_LIST_KEY] = all_lists[0]
            await update.message.reply_text(f"Автоматически выбран единственный список: '{all_lists[0]}'.")

    help_text_lines = [
        f"Привет, {user.mention_html()}! Я бот для управления списками.\n",
        "Вот что я умею:",
        "",
        "<b>Управление списками:</b>",
        f"{Commands.CREATE_LIST} - Создать новый",
        f"{Commands.SHOW_LISTS} - Показать списки",
        f"{Commands.SET_ACTIVE_LIST} - Выбрать список",
        f"{Commands.DELETE_LIST} - Удалить список",
        "",
        "<b>Управление выбранным списком:</b>",
        f"{Commands.ADD_ITEM} - Добавить элемент",
        f"{Commands.SHOW_ITEMS} - Показать элементы",
        f"{Commands.REMOVE_ITEM} - Удалить элемент",
        "",
        f"{Commands.HELP} - Вывести это сообщение",
    ]

    await update.message.reply_html("\n".join(help_text_lines))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start_command(update, context)


async def createlist_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Как назовём новый список?")
    return AWAITING_LISTNAME_FOR_CREATE


async def createlist_receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        return ConversationHandler.END
    new_list_name_raw = update.message.text.strip()
    new_list_name = sanitize_filename(new_list_name_raw)
    if not new_list_name:
        await update.message.reply_text(f"Такое имя не подходит.\nПопробуй ещё раз {Commands.CREATE_LIST}")
        return ConversationHandler.END
    if get_user_list_path(user.id, new_list_name).exists():
        await update.message.reply_text(
            f"Список '{new_list_name}' уже есть.\n"
            f"Выбрать {Commands.SET_ACTIVE_LIST} или создать {Commands.CREATE_LIST} с другим названием"
        )
        return ConversationHandler.END

    write_list(user.id, new_list_name, [])

    context.user_data[CURRENT_LIST_KEY] = new_list_name

    await update.message.reply_text(
        f"Создан и выбран список '{new_list_name}'"
        + f"\n\n{Commands.ADD_ITEM}  {Commands.REMOVE_ITEM}  {Commands.SHOW_ITEMS}"
    )

    return ConversationHandler.END


async def lists_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.message:
        return

    all_lists = get_all_list_names(user.id)
    current_list_name = context.user_data.get(CURRENT_LIST_KEY)

    message_parts = ["Ваши списки:"]
    for i, name in enumerate(all_lists, 1):
        prefix = "🟢 " if name == current_list_name else "⚪ "
        message_parts.append(f"{prefix}{i}. {name}")
    if current_list_name and current_list_name not in all_lists:
        message_parts.append(
            f"\nWarn: Список '{current_list_name}' не существует. {Commands.SET_ACTIVE_LIST} выбрать другой."
        )
        if CURRENT_LIST_KEY in context.user_data:
            del context.user_data[CURRENT_LIST_KEY]
    await update.message.reply_text(
        "\n".join(message_parts) + f"\n\n{Commands.SET_ACTIVE_LIST}  {Commands.CREATE_LIST}  {Commands.DELETE_LIST}  "
    )


async def selectlist_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not user or not update.message:
        return ConversationHandler.END

    all_lists = get_all_list_names(user.id)

    if not all_lists:
        await update.message.reply_text(f"Списков нет. Создать {Commands.CREATE_LIST}")
        return ConversationHandler.END

    current_list_name = context.user_data.get(CURRENT_LIST_KEY)

    # Create inline keyboard with buttons for each list
    keyboard = []
    row = []
    for i, list_name in enumerate(all_lists, 1):
        # Add indicator for current list
        prefix = "🟢 " if list_name == current_list_name else ""
        display_text = f"{prefix}{list_name}"

        # Truncate long list names for button display
        if len(display_text) > 25:
            display_text = display_text[:22] + "..."

        button = InlineKeyboardButton(display_text, callback_data=f"select_{i}")
        row.append(button)

        # Create rows of 2 buttons each for lists
        if len(row) == 2:
            keyboard.append(row)
            row = []

    # Add remaining buttons
    if row:
        keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("Выберите список:", reply_markup=reply_markup)

    return ConversationHandler.END


async def selectlist_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button clicks for list selection"""
    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    await query.answer()

    # Extract list number from callback data (format: "select_N")
    callback_data = query.data
    if not callback_data or not callback_data.startswith("select_"):
        await query.edit_message_text("Ошибка: неверные данные кнопки")
        return

    try:
        list_number = int(callback_data.split("_")[1])
    except (IndexError, ValueError):
        await query.edit_message_text("Ошибка: неверный номер списка")
        return

    all_lists = get_all_list_names(user.id)

    if not (1 <= list_number <= len(all_lists)):
        await query.edit_message_text(f"Неверный номер списка (1-{len(all_lists)})")
        return

    selected_name = all_lists[list_number - 1]
    context.user_data[CURRENT_LIST_KEY] = selected_name

    await query.edit_message_text(f"✓ Выбран список '{selected_name}'")

    # Show items in the selected list
    items = read_list(user.id, selected_name)
    if not items:
        await query.message.reply_text(f"Список '{selected_name}' пуст!\nДобавить элемент - {Commands.ADD_ITEM}")
        return

    message_text_parts = [f"Список '<b>{selected_name}</b>':"]

    for i, item in enumerate(items, 1):
        if "~" in item:
            item = f"<s>{item[1:-1]}</s>"
        message_text_parts.append(f"{i}. {item}")

    await query.message.reply_html(
        "\n".join(message_text_parts) + f"\n\n{Commands.ADD_ITEM}  {Commands.REMOVE_ITEM}",
        reply_markup=get_standard_keyboard(),
    )


async def deletelist_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not user or not update.message:
        return ConversationHandler.END
    all_lists = get_all_list_names(user.id)

    if not all_lists:
        await update.message.reply_text(f"Нет доступных списков. Создать - {Commands.CREATE_LIST}")
        return ConversationHandler.END

    # Filter out 'default' from deletable lists
    deletable_lists = [lst for lst in all_lists if lst != "default"]

    if not deletable_lists:
        await update.message.reply_text("Список 'default' удалять нельзя. Создайте другие списки для удаления.")
        return ConversationHandler.END

    await lists_command(update, context)

    await update.message.reply_text("Введи номер списка для удаления (список 'default' удалять нельзя):")

    return AWAITING_LISTNAME_FOR_DELETE


async def deletelist_receive_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        return ConversationHandler.END
    choice = update.message.text.strip()
    all_lists = get_all_list_names(user.id)
    list_to_delete_name = None
    if choice.isdigit():
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(all_lists):
                list_to_delete_name = all_lists[idx]
        except ValueError:
            pass
    if not list_to_delete_name:
        potential_sanitized_name = sanitize_filename(choice)
        if potential_sanitized_name in all_lists:
            list_to_delete_name = potential_sanitized_name
        elif choice in all_lists:
            list_to_delete_name = choice
    if not list_to_delete_name:
        await update.message.reply_text(f"Список '{choice}' не найден. Попробуй {Commands.DELETE_LIST} ещё раз")
        return ConversationHandler.END

    # Double-check that it's not 'default'
    if list_to_delete_name == "default":
        await update.message.reply_text("Список 'default' удалять нельзя")
        return ConversationHandler.END

    context.user_data[LIST_TO_DELETE_KEY] = list_to_delete_name

    await update.message.reply_text(f"⚠️ Удалить список '{list_to_delete_name}'?\nВведи 'да' для подтверждения.")
    return AWAITING_CONFIRM_DELETE


async def deletelist_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        return ConversationHandler.END
    list_to_delete_name = context.user_data.get(LIST_TO_DELETE_KEY)
    if not list_to_delete_name:
        await update.message.reply_text(f"Error: No list pending deletion. Start with {Commands.DELETE_LIST}")
        return ConversationHandler.END
    confirmation = update.message.text.strip().lower()
    if confirmation == "да":
        list_path = get_user_list_path(user.id, list_to_delete_name)
        if list_path.exists():
            try:
                os.remove(list_path)
                await update.message.reply_text(f"Список '{list_to_delete_name}' удалён")
                # If deleted list was active, switch to 'default'
                if context.user_data.get(CURRENT_LIST_KEY) == list_to_delete_name:
                    context.user_data[CURRENT_LIST_KEY] = "default"
                    await update.message.reply_text("Автоматически выбран список 'default'")
            except OSError:
                await update.message.reply_text(f"Ошибка удаления '{list_to_delete_name}'.")
        else:
            await update.message.reply_text(f"Список '{list_to_delete_name}' не найден.")
    else:
        await update.message.reply_text("Удаления списка отменено")

    context.user_data.pop(LIST_TO_DELETE_KEY, None)

    return ConversationHandler.END


async def add_item_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not user or not update.message:
        return ConversationHandler.END
    current_list_name = await ensure_list_selected(update, context)
    if not current_list_name:
        return ConversationHandler.END

    await update.message.reply_text(f"Какой элемент добавим в '{current_list_name}':")

    return AWAITING_ITEM_FOR_ADD


async def add_item_receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        return ConversationHandler.END
    current_list_name = context.user_data.get(CURRENT_LIST_KEY)
    if not current_list_name:
        await update.message.reply_text(f"Ошибка: Нет выбранного списка. Используй {Commands.SET_ACTIVE_LIST}")
        return ConversationHandler.END

    item_to_add: list = [el.lower() for el in update.message.text.strip().split("  ") if el]

    if not item_to_add:
        await update.message.reply_text(f"Нельзя добавить пустое значение.\nПопробуй ещё раз {Commands.ADD_ITEM}")
        return ConversationHandler.END

    current_items = read_list(user.id, current_list_name)
    current_items.extend(item_to_add)

    write_list(user.id, current_list_name, current_items)

    await update.message.reply_text(f"Элемент '{item_to_add}' дбавлен в список '{current_list_name}'")

    await list_items_command(update, context)

    return ConversationHandler.END


async def list_items_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user

    if not user or not update.message:
        return

    current_list_name = await ensure_list_selected(update, context)
    if not current_list_name:
        return

    items = read_list(user.id, current_list_name)
    if not items:
        await update.message.reply_text(f"Список '{current_list_name}' пуст!\nДобавить элемент - {Commands.ADD_ITEM}")
        return

    message_text_parts = [f"Список '<b>{current_list_name}</b>':"]

    # Check if all items are crossed out
    all_crossed = all("~" in item for item in items)

    for i, item in enumerate(items, 1):
        if "~" in item:
            item = f"<s>{item[1:-1]}</s>"
        message_text_parts.append(f"{i}. {item}")

    # If all items are crossed out and it's not the default list, show delete button
    if all_crossed and current_list_name != "default":
        keyboard = [
            [InlineKeyboardButton("🗑️ Удалить список и вернуться к default", callback_data="delete_completed_list")],
            [
                InlineKeyboardButton("📋 Показать списки", callback_data="show_lists"),
                InlineKeyboardButton("📝 Показать элементы", callback_data="show_items"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_html(
            "\n".join(message_text_parts) + f"\n\n✅ Все элементы вычеркнуты!", reply_markup=reply_markup
        )
    else:
        await update.message.reply_html(
            "\n".join(message_text_parts) + f"\n\n{Commands.ADD_ITEM}  {Commands.REMOVE_ITEM}",
            reply_markup=get_standard_keyboard(),
        )


async def remove_item_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user

    if not user or not update.message:
        return ConversationHandler.END

    current_list_name = await ensure_list_selected(update, context)

    if not current_list_name:
        return ConversationHandler.END

    current_items = read_list(user.id, current_list_name)

    if not current_items:
        await update.message.reply_text(f"Список '{current_list_name}' пуст. Удалять нечего.")
        return ConversationHandler.END

    # Filter out already crossed-out items (those with ~)
    active_items = [(i, item) for i, item in enumerate(current_items, 1) if "~" not in item]

    if not active_items:
        await update.message.reply_text(f"Все элементы в списке '{current_list_name}' уже вычеркнуты. Удалять нечего.")
        return ConversationHandler.END

    # Create inline keyboard with buttons for each active item
    keyboard = []
    row = []
    for i, item in active_items:
        # Truncate long items for button display
        display_text = item
        if len(display_text) > 20:
            display_text = display_text[:17] + "..."

        button = InlineKeyboardButton(f"{i}. {display_text}", callback_data=f"remove_{i}")
        row.append(button)

        # Create rows of 3 buttons each
        if len(row) == 3:
            keyboard.append(row)
            row = []

    # Add remaining buttons
    if row:
        keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Выберите элемент для удаления из списка '{current_list_name}':", reply_markup=reply_markup
    )

    return ConversationHandler.END


async def remove_item_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button clicks for item removal"""
    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    await query.answer()

    current_list_name = context.user_data.get(CURRENT_LIST_KEY)

    if not current_list_name:
        await query.edit_message_text(f"Error: Не выбран список. Выбрать - {Commands.SET_ACTIVE_LIST}")
        return

    # Extract item number from callback data (format: "remove_N")
    callback_data = query.data
    if not callback_data or not callback_data.startswith("remove_"):
        await query.edit_message_text("Ошибка: неверные данные кнопки")
        return

    try:
        item_number = int(callback_data.split("_")[1])
    except (IndexError, ValueError):
        await query.edit_message_text("Ошибка: неверный номер элемента")
        return

    current_items = read_list(user.id, current_list_name)

    if not current_items:
        await query.edit_message_text(f"Список '{current_list_name}' пуст")
        return

    if not (1 <= item_number <= len(current_items)):
        await query.edit_message_text(
            f"Неверный номер элемента (1-{len(current_items)}). Попробуй ещё раз - {Commands.REMOVE_ITEM}"
        )
        return

    # Toggle strikethrough or remove item
    new_items = list(current_items)
    if "~" not in new_items[item_number - 1]:
        new_items[item_number - 1] = f"~{new_items[item_number - 1]}~"
    else:
        new_items[item_number - 1] = ""

    new_items = [el for el in new_items if el]

    write_list(user.id, current_list_name, new_items)

    # Edit the message to show success
    await query.edit_message_text(f"✓ Элемент удалён из списка '{current_list_name}'")

    # Show updated list
    items = read_list(user.id, current_list_name)
    if not items:
        await query.message.reply_text(
            f"Список '{current_list_name}' теперь пуст!\nДобавить элемент - {Commands.ADD_ITEM}"
        )
        return

    message_text_parts = [f"Список '<b>{current_list_name}</b>':"]

    # Check if all items are crossed out
    all_crossed = all("~" in item for item in items)

    for i, item in enumerate(items, 1):
        if "~" in item:
            item = f"<s>{item[1:-1]}</s>"
        message_text_parts.append(f"{i}. {item}")

    # If all items are crossed out and it's not the default list, show delete button
    if all_crossed and current_list_name != "default":
        keyboard = [
            [InlineKeyboardButton("🗑️ Удалить список и вернуться к default", callback_data="delete_completed_list")],
            [
                InlineKeyboardButton("📋 Показать списки", callback_data="show_lists"),
                InlineKeyboardButton("📝 Показать элементы", callback_data="show_items"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_html(
            "\n".join(message_text_parts) + f"\n\n✅ Все элементы вычеркнуты!", reply_markup=reply_markup
        )
    else:
        await query.message.reply_html(
            "\n".join(message_text_parts) + f"\n\n{Commands.ADD_ITEM}  {Commands.REMOVE_ITEM}",
            reply_markup=get_standard_keyboard(),
        )


async def standard_keyboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle standard keyboard button clicks"""
    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    await query.answer()

    callback_data = query.data

    if callback_data == "show_lists":
        # Show lists
        all_lists = get_all_list_names(user.id)
        current_list_name = context.user_data.get(CURRENT_LIST_KEY)

        message_parts = ["Ваши списки:"]
        for i, name in enumerate(all_lists, 1):
            prefix = "🟢 " if name == current_list_name else "⚪ "
            message_parts.append(f"{prefix}{i}. {name}")

        await query.message.reply_text(
            "\n".join(message_parts) + f"\n\n{Commands.SET_ACTIVE_LIST}  {Commands.DELETE_LIST}  {Commands.HELP}",
            reply_markup=get_standard_keyboard(),
        )

    elif callback_data == "show_items":
        # Show items in current list
        current_list_name = context.user_data.get(CURRENT_LIST_KEY)

        if not current_list_name:
            await query.message.reply_text(
                "Не выбран список!\nИспользуйте кнопку '📋 Показать списки' чтобы выбрать список",
                reply_markup=get_standard_keyboard(),
            )
            return

        items = read_list(user.id, current_list_name)
        if not items:
            await query.message.reply_text(f"Список '{current_list_name}' пуст!", reply_markup=get_standard_keyboard())
            return

        message_text_parts = [f"Список '<b>{current_list_name}</b>':"]
        all_crossed = all("~" in item for item in items)

        for i, item in enumerate(items, 1):
            if "~" in item:
                item = f"<s>{item[1:-1]}</s>"
            message_text_parts.append(f"{i}. {item}")

        # If all items are crossed out and it's not the default list, show delete button
        if all_crossed and current_list_name != "default":
            keyboard = [
                [InlineKeyboardButton("🗑️ Удалить список и вернуться к default", callback_data="delete_completed_list")],
                [
                    InlineKeyboardButton("📋 Показать списки", callback_data="show_lists"),
                    InlineKeyboardButton("📝 Показать элементы", callback_data="show_items"),
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_html(
                "\n".join(message_text_parts) + f"\n\n✅ Все элементы вычеркнуты!", reply_markup=reply_markup
            )
        else:
            await query.message.reply_html(
                "\n".join(message_text_parts) + f"\n\n{Commands.ADD_ITEM}  {Commands.REMOVE_ITEM}",
                reply_markup=get_standard_keyboard(),
            )


async def delete_completed_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle deletion of completed list and switch to default"""
    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    await query.answer()

    current_list_name = context.user_data.get(CURRENT_LIST_KEY)

    if not current_list_name or current_list_name == "default":
        await query.edit_message_text("Ошибка: нельзя удалить список 'default'")
        return

    # Delete the list file
    list_path = get_user_list_path(user.id, current_list_name)
    if list_path.exists():
        try:
            os.remove(list_path)
            # Switch to default list
            context.user_data[CURRENT_LIST_KEY] = "default"
            await query.edit_message_text(f"✓ Список '{current_list_name}' удалён. Выбран список 'default'")

            # Show default list items
            items = read_list(user.id, "default")
            if not items:
                await query.message.reply_text(f"Список 'default' пуст!\nДобавить элемент - {Commands.ADD_ITEM}")
                return

            message_text_parts = [f"Список '<b>default</b>':"]

            for i, item in enumerate(items, 1):
                if "~" in item:
                    item = f"<s>{item[1:-1]}</s>"
                message_text_parts.append(f"{i}. {item}")

            await query.message.reply_html(
                "\n".join(message_text_parts) + f"\n\n{Commands.ADD_ITEM}  {Commands.REMOVE_ITEM}",
                reply_markup=get_standard_keyboard(),
            )
        except OSError:
            await query.edit_message_text(f"Ошибка удаления списка '{current_list_name}'")
    else:
        await query.edit_message_text(f"Список '{current_list_name}' не найден")


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            f"Нарушен контекст или неизвестная команда {update.message.text}\n{Commands.HELP} to see the menu"
        )


async def post_init_tasks(application: Application) -> None:
    """Tasks to run after the bot is initialized but before polling starts."""
    bot_commands = [
        BotCommand("start", "Start the bot & see help"),
        BotCommand(Commands.HELP, "Show help message"),
        BotCommand(Commands.CREATE_LIST, "Create a new purchase list"),
        BotCommand(Commands.SHOW_LISTS, "Show all your purchase lists"),
        BotCommand(Commands.SET_ACTIVE_LIST, "Select an active purchase list"),
        BotCommand(Commands.DELETE_LIST, "Delete a purchase list"),
        BotCommand(Commands.ADD_ITEM, "Add an item to the current list"),
        BotCommand(Commands.SHOW_ITEMS, "Show items in the current list"),
        BotCommand(Commands.REMOVE_ITEM, "Remove item from current list"),
        BotCommand(Commands.CANCEL, "Cancel operation"),
    ]
    await application.bot.set_my_commands(bot_commands)
    logger.info("Bot commands have been set")


def main() -> None:
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.error("ERROR: TELEGRAM_BOT_TOKEN not set")
        return

    USER_DATA_BASE_DIR.mkdir(parents=True, exist_ok=True)

    application = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init_tasks)  # Add post_init hook
        .build()
    )

    cancel_handler = CommandHandler(Commands.CANCEL[1:], cancel_conversation)

    createlist_conv = ConversationHandler(
        entry_points=[CommandHandler(Commands.CREATE_LIST[1:], createlist_entry)],
        states={
            AWAITING_LISTNAME_FOR_CREATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, createlist_receive_name)]
        },
        fallbacks=[cancel_handler],
        conversation_timeout=DEFAULT_TIMEOUT,
    )
    # Select list now uses inline keyboard buttons with callback handler
    selectlist_handler = CommandHandler(Commands.SET_ACTIVE_LIST[1:], selectlist_entry)
    selectlist_callback_handler = CallbackQueryHandler(selectlist_callback, pattern="^select_")
    deletelist_conv = ConversationHandler(
        entry_points=[CommandHandler(Commands.DELETE_LIST[1:], deletelist_entry)],
        states={
            AWAITING_LISTNAME_FOR_DELETE: [MessageHandler(filters.TEXT & ~filters.COMMAND, deletelist_receive_choice)],
            AWAITING_CONFIRM_DELETE: [MessageHandler(filters.TEXT & ~filters.COMMAND, deletelist_confirm)],
        },
        fallbacks=[cancel_handler],
        conversation_timeout=DEFAULT_TIMEOUT,
    )
    add_item_conv = ConversationHandler(
        entry_points=[CommandHandler(Commands.ADD_ITEM[1:], add_item_entry)],
        states={AWAITING_ITEM_FOR_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_item_receive_name)]},
        fallbacks=[cancel_handler],
        conversation_timeout=DEFAULT_TIMEOUT,
    )
    # Remove item now uses inline keyboard buttons with callback handler
    remove_item_handler = CommandHandler(Commands.REMOVE_ITEM[1:], remove_item_entry)
    remove_item_callback_handler = CallbackQueryHandler(remove_item_callback, pattern="^remove_")

    # Delete completed list callback handler
    delete_completed_callback_handler = CallbackQueryHandler(
        delete_completed_list_callback, pattern="^delete_completed_list$"
    )

    # Standard keyboard callback handler
    standard_keyboard_handler = CallbackQueryHandler(standard_keyboard_callback, pattern="^(show_lists|show_items)$")

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler(Commands.HELP[1:], help_command))
    application.add_handler(CommandHandler(Commands.SHOW_LISTS[1:], lists_command))
    application.add_handler(CommandHandler(Commands.SHOW_ITEMS[1:], list_items_command))

    application.add_handler(createlist_conv)
    application.add_handler(selectlist_handler)
    application.add_handler(selectlist_callback_handler)
    application.add_handler(deletelist_conv)
    application.add_handler(add_item_conv)
    application.add_handler(remove_item_handler)
    application.add_handler(remove_item_callback_handler)
    application.add_handler(delete_completed_callback_handler)
    application.add_handler(standard_keyboard_handler)

    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    print("Bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    print("Bot stopped.")


if __name__ == "__main__":
    main()
