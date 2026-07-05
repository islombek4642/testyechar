"""FSM states: which mode the chat is in."""
from aiogram.fsm.state import State, StatesGroup


class Mode(StatesGroup):
    test_waiting = State()
    choosing_model = State()
    managing_users = State()
    adding_user = State()
