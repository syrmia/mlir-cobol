# ─────────────────────────────────────────────────────────────────────────────
#  Main processing
# ─────────────────────────────────────────────────────────────────────────────
def process_node(elem, ident=0, lines=None):
    if lines is None:
        lines = []

    handler = Handlers.get(elem.tag)
    if handler is not None:
        lines.append(handler(elem))

    for child in elem:
        process_node(child, ident + 1, lines)

    return lines


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
def extractText(elem, tag):
    return "".join(txt.text.strip()
                   for cons in elem.findall(f".//{tag}")
                   for txt in cons.findall(".//t")
                   if txt.text)



# ─────────────────────────────────────────────────────────────────────────────
#  Handler methods
# ─────────────────────────────────────────────────────────────────────────────
def handle_programIdParagraph(elem):
    return {"PROGRAM-ID": extractText(elem, "alphanumericConstant")}

def handle_displayStatement(elem):
    return {"DISPLAY": extractText(elem, "alphanumericLiteral")}

def handle_stopStatement(elem):
    return {"STOP": "RUN"}

# ...


# ─────────────────────────────────────────────────────────────────────────────
#  Handlers dictionary
# ─────────────────────────────────────────────────────────────────────────────
Handlers = {
    "programIdParagraph" : handle_programIdParagraph,
    "displayStatement" : handle_displayStatement,
    "stopStatement" : handle_stopStatement
    # ...
}
