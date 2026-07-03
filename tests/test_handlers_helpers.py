from bot.handlers import file_ext, export_keyboard, PARSER_EXTS, RESOLVER_EXTS


def test_file_ext():
    assert file_ext("Test.PDF") == "pdf"
    assert file_ext("archive.tar.gz") == "gz"
    assert file_ext("noext") == ""
    assert file_ext(None) == ""


def test_ext_sets():
    assert PARSER_EXTS == {"pdf", "docx", "doc", "xlsx", "txt"}
    assert RESOLVER_EXTS == {"txt", "docx"}


def test_export_keyboard_callback_data():
    kb = export_keyboard("parser")
    buttons = kb.inline_keyboard[0]
    assert [b.callback_data for b in buttons] == ["exp:parser:txt", "exp:parser:docx"]
