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
    TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"

USER_DATA_BASE_DIR = Path("user_purchase_lists")
CURRENT_LIST_KEY = "current_list_name"
LIST_TO_DELETE_KEY = "list_to_delete_temp_name"

(
    AWAITING_ITEM_FOR_ADD,
    AWAITING_ITEM_FOR_REMOVE,
    AWAITING_LISTNAME_FOR_CREATE,
    AWAITING_LISTNAME_FOR_SELECT,
    AWAITING_LISTNAME_FOR_DELETE,
    AWAITING_CONFIRM_DELETE,
) = range(6)


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
            "No purchase list is currently selected.\n"
            "Use /createlist to make one, or /selectlist to choose one.\n"
            "Use /lists to see all your lists."
        )
        return None
    if not get_user_list_path(user.id, current_list_name).exists():
        await update.message.reply_text(
            f"Selected list '{current_list_name}' no longer exists.\n"
            "Please /selectlist another or /createlist a new one."
        )
        if CURRENT_LIST_KEY in context.user_data:
            del context.user_data[CURRENT_LIST_KEY]
        return None
    return current_list_name


async def cancel_conversation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.message.reply_text("Operation cancelled.")
    context.user_data.pop(LIST_TO_DELETE_KEY, None)
    # Potentially clear other conversation-specific keys if you add more
    return ConversationHandler.END


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.message:
        return
    get_user_dir(user.id)
    all_lists = get_all_list_names(user.id)
    if len(all_lists) == 1 and not context.user_data.get(CURRENT_LIST_KEY):
        context.user_data[CURRENT_LIST_KEY] = all_lists[0]
        await update.message.reply_text(
            f"Automatically selected your only list: '{all_lists[0]}'."
        )

    help_text_lines = [
        f"Hi {user.mention_html()}! I'm your multi-list Purchase Bot. 🛒",
        "Send a command, and I'll ask for more info if needed.",
        "Use the menu button (or type '/') to see available commands.",
        "",
        "<b>List Management:</b>",
        "/createlist - Create a new list.",
        "/lists - Show all your lists.",
        "/selectlist - Select a list to work with.",
        "/deletelist - Delete a list.",
        "",
        "<b>Item Management (for the selected list):</b>",
        "/add - Add item to current list.",
        "/list - Show items in current list.",
        "/remove - Remove item from current list.",
        "/clear - Clear all items from current list.",
        "",
        "/help - Show this message again.",
        "/cancel - Cancel current operation.",
    ]
    await update.message.reply_html("\n".join(help_text_lines))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start_command(update, context)


async def createlist_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("What name would you like for the new list?")
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
        await update.message.reply_text("Invalid list name. Try /createlist again.")
        return ConversationHandler.END
    if get_user_list_path(user.id, new_list_name).exists():
        await update.message.reply_text(
            f"List '{new_list_name}' already exists. Try /selectlist {new_list_name} or /createlist with a new name."
        )
        return ConversationHandler.END
    write_list(user.id, new_list_name, [])
    context.user_data[CURRENT_LIST_KEY] = new_list_name
    await update.message.reply_text(
        f"Created and selected new list: '{new_list_name}'."
    )
    return ConversationHandler.END


async def lists_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.message:
        return
    all_lists = get_all_list_names(user.id)
    current_list_name = context.user_data.get(CURRENT_LIST_KEY)
    if not all_lists:
        await update.message.reply_text("You have no lists. Use /createlist.")
        return
    message_parts = ["Your Purchase Lists:"]
    for i, name in enumerate(all_lists, 1):
        prefix = "➡️ " if name == current_list_name else "   "
        message_parts.append(f"{prefix}{i}. {name}")
    if not current_list_name and len(all_lists) > 0:
        message_parts.append("\nNo list selected. Use /selectlist.")
    elif current_list_name and current_list_name not in all_lists:
        message_parts.append(
            f"\nWarn: Selected list '{current_list_name}' missing. /selectlist another."
        )
        if CURRENT_LIST_KEY in context.user_data:
            del context.user_data[CURRENT_LIST_KEY]
    await update.message.reply_text("\n".join(message_parts))


async def selectlist_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not user or not update.message:
        return ConversationHandler.END
    all_lists = get_all_list_names(user.id)
    if not all_lists:
        await update.message.reply_text("No lists to select. Use /createlist.")
        return ConversationHandler.END
    await lists_command(update, context)
    await update.message.reply_text("Enter name or number of list to select:")
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
        await update.message.reply_text(f"Selected list: '{selected_name}'.")
    else:
        await update.message.reply_text(
            f"List '{choice}' not found. Try /selectlist again or /lists."
        )
    return ConversationHandler.END


async def deletelist_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not user or not update.message:
        return ConversationHandler.END
    all_lists = get_all_list_names(user.id)
    if not all_lists:
        await update.message.reply_text("No lists to delete. Use /createlist.")
        return ConversationHandler.END
    await lists_command(update, context)
    await update.message.reply_text("Enter name or number of list to delete:")
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
            f"List '{choice}' not found. Try /deletelist again."
        )
        return ConversationHandler.END
    context.user_data[LIST_TO_DELETE_KEY] = list_to_delete_name
    await update.message.reply_text(
        f"⚠️ Delete list '{list_to_delete_name}'? Reply 'yes' to confirm."
    )
    return AWAITING_CONFIRM_DELETE


async def deletelist_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        return ConversationHandler.END
    list_to_delete_name = context.user_data.get(LIST_TO_DELETE_KEY)
    if not list_to_delete_name:
        await update.message.reply_text(
            "Error: No list pending deletion. Start with /deletelist."
        )
        return ConversationHandler.END
    confirmation = update.message.text.strip().lower()
    if confirmation == "yes":
        list_path = get_user_list_path(user.id, list_to_delete_name)
        if list_path.exists():
            try:
                os.remove(list_path)
                await update.message.reply_text(
                    f"List '{list_to_delete_name}' deleted."
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
                f"List '{list_to_delete_name}' not found (already deleted?)."
            )
    else:
        await update.message.reply_text("List deletion cancelled.")
    context.user_data.pop(LIST_TO_DELETE_KEY, None)
    return ConversationHandler.END


async def add_item_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not user or not update.message:
        return ConversationHandler.END
    current_list_name = await ensure_list_selected(update, context)
    if not current_list_name:
        return ConversationHandler.END
    await update.message.reply_text(f"Item to add to '{current_list_name}':")
    return AWAITING_ITEM_FOR_ADD


async def add_item_receive_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        return ConversationHandler.END
    current_list_name = context.user_data.get(CURRENT_LIST_KEY)
    if not current_list_name:
        await update.message.reply_text("Error: No list selected. Use /selectlist.")
        return ConversationHandler.END
    item_to_add = update.message.text.strip()
    if not item_to_add:
        await update.message.reply_text("Cannot add empty item. Try /add again.")
        return ConversationHandler.END
    current_items = read_list(user.id, current_list_name)
    if item_to_add.lower() in [item.lower() for item in current_items]:
        await update.message.reply_text(
            f"'{item_to_add}' is already in '{current_list_name}'."
        )
    else:
        current_items.append(item_to_add)
        write_list(user.id, current_list_name, current_items)
        await update.message.reply_text(
            f"Added '{item_to_add}' to list '{current_list_name}'."
        )
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
            f"List '{current_list_name}' is empty! Use /add."
        )
        return
    message_text_parts = [f"<b>Items in '{current_list_name}':</b>"]
    for i, item in enumerate(items, 1):
        message_text_parts.append(f"{i}. {item}")
    await update.message.reply_html("\n".join(message_text_parts))


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
            f"List '{current_list_name}' is empty. Nothing to remove."
        )
        return ConversationHandler.END
    await update.message.reply_text(
        f"Item (name or number) to remove from '{current_list_name}':"
    )
    return AWAITING_ITEM_FOR_REMOVE


async def remove_item_receive_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        return ConversationHandler.END
    current_list_name = context.user_data.get(CURRENT_LIST_KEY)
    if not current_list_name:
        await update.message.reply_text("Error: No list selected. Use /selectlist.")
        return ConversationHandler.END
    item_to_remove_str = update.message.text.strip()
    current_items = read_list(user.id, current_list_name)
    if not current_items:
        await update.message.reply_text(f"List '{current_list_name}' is empty.")
        return ConversationHandler.END
    removed_item_name = None
    new_items = list(current_items)
    if item_to_remove_str.isdigit():
        item_number = int(item_to_remove_str)
        if 1 <= item_number <= len(new_items):
            removed_item_name = new_items.pop(item_number - 1)
        else:
            await update.message.reply_text(
                f"Invalid item number (1-{len(current_items)}). Try /remove again."
            )
            return (
                ConversationHandler.END
            )  # Keep in conversation for retry? For now, end.
    else:
        item_to_remove_lower = item_to_remove_str.lower()
        found_idx = -1
        for i, item_in_list in enumerate(new_items):
            if item_in_list.lower() == item_to_remove_lower:
                found_idx = i
                break
        if found_idx != -1:
            removed_item_name = new_items.pop(found_idx)
    if removed_item_name:
        write_list(user.id, current_list_name, new_items)
        await update.message.reply_text(
            f"Removed '{removed_item_name}' from '{current_list_name}'."
        )
    else:
        await update.message.reply_text(
            f"'{item_to_remove_str}' not found in '{current_list_name}'. Try /remove again."
        )
    return ConversationHandler.END


async def clear_list_command(
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
        await update.message.reply_text(f"List '{current_list_name}' is already empty.")
        return
    write_list(user.id, current_list_name, [])
    await update.message.reply_text(
        f"All items cleared from list '{current_list_name}'."
    )


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text("Unknown command. Try /help or use the menu.")


async def post_init_tasks(application: Application) -> None:
    """Tasks to run after the bot is initialized but before polling starts."""
    bot_commands = [
        BotCommand("start", "Start the bot & see help"),
        BotCommand("help", "Show help message"),
        BotCommand("createlist", "Create a new purchase list"),
        BotCommand("lists", "Show all your purchase lists"),
        BotCommand("selectlist", "Select an active purchase list"),
        BotCommand("deletelist", "Delete a purchase list"),
        BotCommand("add", "Add an item to the current list"),
        BotCommand("list", "Show items in the current list"),
        BotCommand("remove", "Remove item from current list"),
        BotCommand("clear", "Clear all items from current list"),
        BotCommand("cancel", "Cancel the current operation (add/remove etc.)"),
    ]
    await application.bot.set_my_commands(bot_commands)
    print("Bot commands have been set.")


def main() -> None:
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print("ERROR: TELEGRAM_BOT_TOKEN not set.")
        return

    USER_DATA_BASE_DIR.mkdir(parents=True, exist_ok=True)

    application = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init_tasks)  # Add post_init hook
        .build()
    )

    cancel_handler = CommandHandler("cancel", cancel_conversation)
    createlist_conv = ConversationHandler(
        entry_points=[CommandHandler("createlist", createlist_entry)],
        states={
            AWAITING_LISTNAME_FOR_CREATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, createlist_receive_name)
            ]
        },
        fallbacks=[cancel_handler],
        conversation_timeout=300,
    )
    selectlist_conv = ConversationHandler(
        entry_points=[CommandHandler("selectlist", selectlist_entry)],
        states={
            AWAITING_LISTNAME_FOR_SELECT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, selectlist_receive_choice
                )
            ]
        },
        fallbacks=[cancel_handler],
        conversation_timeout=300,
    )
    deletelist_conv = ConversationHandler(
        entry_points=[CommandHandler("deletelist", deletelist_entry)],
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
        conversation_timeout=300,
    )
    add_item_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_item_entry)],
        states={
            AWAITING_ITEM_FOR_ADD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_item_receive_name)
            ]
        },
        fallbacks=[cancel_handler],
        conversation_timeout=300,
    )
    remove_item_conv = ConversationHandler(
        entry_points=[CommandHandler("remove", remove_item_entry)],
        states={
            AWAITING_ITEM_FOR_REMOVE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, remove_item_receive_choice
                )
            ]
        },
        fallbacks=[cancel_handler],
        conversation_timeout=300,
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("lists", lists_command))
    application.add_handler(CommandHandler("list", list_items_command))
    application.add_handler(CommandHandler("clear", clear_list_command))

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
