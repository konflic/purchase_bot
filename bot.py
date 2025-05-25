import os
import re
from pathlib import Path
from telegram import Update, BotCommand
from telegram.ext import (
    Application,  # Added for type hinting in post_init
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
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
    AWAITING_ITEM_FOR_REMOVE,
    AWAITING_LISTNAME_FOR_CREATE,
    AWAITING_LISTNAME_FOR_SELECT,
    AWAITING_LISTNAME_FOR_DELETE,
    AWAITING_CONFIRM_DELETE,
) = range(6)


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
    return sorted([p.stem for p in user_dir.glob("*.txt") if p.is_file()])


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


async def ensure_list_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> str | None:
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


async def cancel_conversation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
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
    if len(all_lists) == 1 and not context.user_data.get(CURRENT_LIST_KEY):
        context.user_data[CURRENT_LIST_KEY] = all_lists[0]
        await update.message.reply_text(
            f"Автоматически выбрат единственный список: '{all_lists[0]}'."
        )

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


async def createlist_receive_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        return ConversationHandler.END
    new_list_name_raw = update.message.text.strip()
    new_list_name = sanitize_filename(new_list_name_raw)
    if not new_list_name:
        await update.message.reply_text(
            f"Такое имя не подходит.\nПопробуй ещё разок {Commands.CREATE_LIST}"
        )
        return ConversationHandler.END
    if get_user_list_path(user.id, new_list_name).exists():
        await update.message.reply_text(
            f"Список '{new_list_name}' уже есть.\n"
            f"Попробуй {Commands.SET_ACTIVE_LIST} или {Commands.CREATE_LIST} с другим названием"
        )
        return ConversationHandler.END
    write_list(user.id, new_list_name, [])
    context.user_data[CURRENT_LIST_KEY] = new_list_name
    await update.message.reply_text(f"Ура! Создан и выбран список '{new_list_name}'")
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
            f"\nWarn: Selected list '{current_list_name}' missing. {Commands.SET_ACTIVE_LIST} another."
        )
        if CURRENT_LIST_KEY in context.user_data:
            del context.user_data[CURRENT_LIST_KEY]
    await update.message.reply_text(
        "\n".join(message_parts) + f"\n\n{Commands.SET_ACTIVE_LIST}"
    )


async def selectlist_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not user or not update.message:
        return ConversationHandler.END
    all_lists = get_all_list_names(user.id)
    if not all_lists:
        await update.message.reply_text(
            f"Списков нет. Создать - {Commands.CREATE_LIST}"
        )
        return ConversationHandler.END
    await lists_command(update, context)
    await update.message.reply_text("Введи номер списка:")
    return AWAITING_LISTNAME_FOR_SELECT


async def selectlist_receive_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        return ConversationHandler.END
    choice = update.message.text.strip()
    all_lists = get_all_list_names(user.id)
    selected_name = None
    if choice.isdigit():
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(all_lists):
                selected_name = all_lists[idx]
        except ValueError:
            pass
    if not selected_name:
        potential_sanitized_name = sanitize_filename(choice)
        if potential_sanitized_name in all_lists:
            selected_name = potential_sanitized_name
        elif choice in all_lists:
            selected_name = choice
    if selected_name:
        context.user_data[CURRENT_LIST_KEY] = selected_name
        await update.message.reply_text(f"Выбран список '{selected_name}'")
        await list_items_command(update, context)
    else:
        await update.message.reply_text(
            f"Список '{choice}' не найден.\nПопробуй {Commands.SET_ACTIVE_LIST} ещё раз с одним из доступных списков {Commands.SHOW_LISTS}"
        )
    return ConversationHandler.END


async def deletelist_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not user or not update.message:
        return ConversationHandler.END
    all_lists = get_all_list_names(user.id)
    if not all_lists:
        await update.message.reply_text(
            f"Нет доступных списков. Создать - {Commands.CREATE_LIST}."
        )
        return ConversationHandler.END
    await lists_command(update, context)
    await update.message.reply_text("Введи номер списка для удаления:")
    return AWAITING_LISTNAME_FOR_DELETE


async def deletelist_receive_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
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
        await update.message.reply_text(
            f"List '{choice}' not found. Try {Commands.DELETE_LIST} again"
        )
        return ConversationHandler.END

    context.user_data[LIST_TO_DELETE_KEY] = list_to_delete_name

    if list_to_delete_name == "default":
        await update.message.reply_text("Список default удалять нельзя")
        await lists_command(update, context)
        return ConversationHandler.END

    await update.message.reply_text(
        f"⚠️ Удалить список '{list_to_delete_name}'?\nВведи 'да' для подтверждения."
    )
    return AWAITING_CONFIRM_DELETE


async def deletelist_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        return ConversationHandler.END
    list_to_delete_name = context.user_data.get(LIST_TO_DELETE_KEY)
    if not list_to_delete_name:
        await update.message.reply_text(
            f"Error: No list pending deletion. Start with {Commands.DELETE_LIST}"
        )
        return ConversationHandler.END
    confirmation = update.message.text.strip().lower()
    if confirmation == "да":
        list_path = get_user_list_path(user.id, list_to_delete_name)
        if list_path.exists():
            try:
                os.remove(list_path)
                await update.message.reply_text(
                    f"Список '{list_to_delete_name}' удалён"
                )
                if context.user_data.get(CURRENT_LIST_KEY) == list_to_delete_name:
                    if CURRENT_LIST_KEY in context.user_data:
                        del context.user_data[CURRENT_LIST_KEY]
            except OSError:
                await update.message.reply_text(
                    f"Error deleting '{list_to_delete_name}'."
                )
        else:
            await update.message.reply_text(
                f"Список '{list_to_delete_name}' не найден."
            )
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


async def add_item_receive_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        return ConversationHandler.END
    current_list_name = context.user_data.get(CURRENT_LIST_KEY)
    if not current_list_name:
        await update.message.reply_text(
            f"Error: No list selected. Use {Commands.SET_ACTIVE_LIST}"
        )
        return ConversationHandler.END

    item_to_add: list = [
        el.lower() for el in update.message.text.strip().split("  ") if el
    ]

    if not item_to_add:
        await update.message.reply_text(
            f"Нельзя добавить пустое значение.\nПопробуй ещё раз {Commands.ADD_ITEM}"
        )
        return ConversationHandler.END

    current_items = read_list(user.id, current_list_name)
    current_items.extend(item_to_add)

    write_list(user.id, current_list_name, current_items)

    await update.message.reply_text(
        f"Элемент '{item_to_add}' дбавлен в список '{current_list_name}'"
    )

    await list_items_command(update, context)
    return ConversationHandler.END


async def list_items_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    if not user or not update.message:
        return
    current_list_name = await ensure_list_selected(update, context)
    if not current_list_name:
        return
    items = read_list(user.id, current_list_name)
    if not items:
        await update.message.reply_text(
            f"Список '{current_list_name}' пуст!\nДобавить элемент - {Commands.ADD_ITEM}"
        )
        return
    message_text_parts = [f"List '<b>{current_list_name}</b>':"]
    for i, item in enumerate(items, 1):
        message_text_parts.append(f"{i}. {item}")
    await update.message.reply_html(
        "\n".join(message_text_parts)
        + f"\n\n{Commands.ADD_ITEM}  {Commands.REMOVE_ITEM}  {Commands.HELP}"
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
        await update.message.reply_text(
            f"Список '{current_list_name}' пуст. Удалять нечего."
        )
        return ConversationHandler.END

    await update.message.reply_text(f"Номер элемента для удаления:")

    return AWAITING_ITEM_FOR_REMOVE


async def remove_item_receive_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        return ConversationHandler.END

    current_list_name = context.user_data.get(CURRENT_LIST_KEY)

    if not current_list_name:
        await update.message.reply_text(
            f"Error: Не выбран список. Выбрать - {Commands.SET_ACTIVE_LIST}"
        )
        return ConversationHandler.END

    items_to_remove: list = [el for el in update.message.text.strip().split(" ") if el]

    current_items = read_list(user.id, current_list_name)

    if not current_items:
        await update.message.reply_text(f"Список '{current_list_name}' пуст")
        return ConversationHandler.END

    removed_item_names = []

    new_items = list(current_items)

    for item in items_to_remove:
        if item.isdigit():
            item_number = int(item)
            if 1 <= item_number <= len(new_items):
                removed_item_names.append(new_items[item_number - 1])
                new_items[item_number - 1] = ""
            else:
                await update.message.reply_text(
                    f"Неверный номер элемента (1-{len(current_items)}). Попробуй ещё раз - {Commands.REMOVE_ITEM}"
                )
                return ConversationHandler.END

    new_items = [el for el in new_items if el]

    if removed_item_names:

        write_list(user.id, current_list_name, new_items)

        await update.message.reply_text(
            f"Удалён элемент '{removed_item_names}' из списка '{current_list_name}'"
        )
    else:
        await update.message.reply_text(
            f"'{items_to_remove}' не найден в списке '{current_list_name}'"
        )

    await list_items_command(update, context)

    return ConversationHandler.END


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
    print("Bot commands have been set")


def main() -> None:
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print("ERROR: TELEGRAM_BOT_TOKEN not set")
        return

    USER_DATA_BASE_DIR.mkdir(parents=True, exist_ok=True)

    application = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init_tasks)  # Add post_init hook
        .build()
    )

    cancel_handler = CommandHandler(Commands.CANCEL, cancel_conversation)

    createlist_conv = ConversationHandler(
        entry_points=[CommandHandler(Commands.CREATE_LIST, createlist_entry)],
        states={
            AWAITING_LISTNAME_FOR_CREATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, createlist_receive_name)
            ]
        },
        fallbacks=[cancel_handler],
        conversation_timeout=DEFAULT_TIMEOUT,
    )
    selectlist_conv = ConversationHandler(
        entry_points=[CommandHandler(Commands.SET_ACTIVE_LIST, selectlist_entry)],
        states={
            AWAITING_LISTNAME_FOR_SELECT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, selectlist_receive_choice
                )
            ]
        },
        fallbacks=[cancel_handler],
        conversation_timeout=DEFAULT_TIMEOUT,
    )
    deletelist_conv = ConversationHandler(
        entry_points=[CommandHandler(Commands.DELETE_LIST, deletelist_entry)],
        states={
            AWAITING_LISTNAME_FOR_DELETE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, deletelist_receive_choice
                )
            ],
            AWAITING_CONFIRM_DELETE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, deletelist_confirm)
            ],
        },
        fallbacks=[cancel_handler],
        conversation_timeout=DEFAULT_TIMEOUT,
    )
    add_item_conv = ConversationHandler(
        entry_points=[CommandHandler(Commands.ADD_ITEM, add_item_entry)],
        states={
            AWAITING_ITEM_FOR_ADD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_item_receive_name)
            ]
        },
        fallbacks=[cancel_handler],
        conversation_timeout=DEFAULT_TIMEOUT,
    )
    remove_item_conv = ConversationHandler(
        entry_points=[CommandHandler(Commands.REMOVE_ITEM, remove_item_entry)],
        states={
            AWAITING_ITEM_FOR_REMOVE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, remove_item_receive_choice
                )
            ]
        },
        fallbacks=[cancel_handler],
        conversation_timeout=DEFAULT_TIMEOUT,
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler(Commands.HELP, help_command))
    application.add_handler(CommandHandler(Commands.SHOW_LISTS, lists_command))
    application.add_handler(CommandHandler(Commands.SHOW_ITEMS, list_items_command))

    application.add_handler(createlist_conv)
    application.add_handler(selectlist_conv)
    application.add_handler(deletelist_conv)
    application.add_handler(add_item_conv)
    application.add_handler(remove_item_conv)

    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    print("Bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    print("Bot stopped.")


if __name__ == "__main__":
    main()
