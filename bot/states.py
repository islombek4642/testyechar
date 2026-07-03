"""FSM states: which mode the chat is in."""
from aiogram.fsm.state import State, StatesGroup


class Mode(StatesGroup):
    parser_waiting = State()
    resolver_waiting = State()
