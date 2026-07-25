from smartcli.output_style import normalize_terminal_markdown


def test_normalizer_reduces_markdown_to_terminal_subset():
    source = """# Result

> quoted text

1. first
   - nested

---

```python
# keep this comment
if ready:
    print(`value`)
```

**whole paragraph**
"""
    assert normalize_terminal_markdown(source) == (
        "### Result\n\nquoted text\n\n- first\n- nested\n\n"
        "# keep this comment\nif ready:\n    print(`value`)\n\nwhole paragraph"
    )


def test_normalizer_converts_tables_to_flat_lists():
    source = """| Risk | Fix |
| :--- | ---: |
| High | Validate input |
| Low | Add **tests** |"""
    assert normalize_terminal_markdown(source) == (
        "- **Risk**: High; **Fix**: Validate input\n"
        "- **Risk**: Low; **Fix**: Add **tests**"
    )


def test_normalizer_collapses_blank_lines_and_preserves_inline_markup():
    source = "## Notes\n\n\nUse `doctor` for **diagnostics**."
    assert normalize_terminal_markdown(source) == (
        "### Notes\n\nUse `doctor` for **diagnostics**."
    )
