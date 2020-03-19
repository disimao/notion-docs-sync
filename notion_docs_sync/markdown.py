import logging
import re
import collections
from notion.block import CodeBlock, DividerBlock, HeaderBlock, SubheaderBlock, \
    SubsubheaderBlock, QuoteBlock, TextBlock, NumberedListBlock, \
    BulletedListBlock, ImageBlock, CollectionViewBlock
import mistletoe
from mistletoe.base_renderer import BaseRenderer


logger = logging.getLogger(__name__)


def flatten(l):
    for el in l:
        if isinstance(el, collections.Iterable) and not isinstance(el, (str, bytes, dict)):
            yield from flatten(el)
        else:
            yield el

class NotionRenderer(BaseRenderer):
    """
    A class that will render out a Markdown file into a descriptor for upload
    with notion-py. Each object will have a .type for the block type and then
    a bunch of different dict entries corresponding to kwargs for that block
    type.
    For CollectionViewBlocks, a .rows entry exists in the dictionary with a list
    object containing a descriptor for every row. This is still TODO
    """

    def render(self, token):
        """
        Takes a single Markdown token and renders it down to
        NotionPy classes. Note that all the recursion is handled in the delegated
        methods.
        Overrides super().render but still uses render_map and then just
        does special parsing for stuff
        """
        return self.render_map[token.__class__.__name__](token)

    def render_multiple(self, tokens):
        """
        Takes an array of sibling tokens and renders each one out.
        """
        return list(flatten(self.render(t) for t in tokens))

    def render_multiple_to_string(self, tokens):
        """
        Takes tokens and render them to a single string (if possible). Anything it
        can't convert to a string will be returned in the second part of the tuple
        @param {objects} tokens
        @returns {tuple} (str, dict[])
        """
        def toString(renderedBlock):
            if isinstance(renderedBlock, dict) and renderedBlock['type'] == TextBlock:
                return renderedBlock['title'] #This unwraps TextBlocks/paragraphs to use in other blocks
            else: #Returns str as-is or returns blocks we can't convert
                return renderedBlock

        #Try to convert any objects to strings
        rendered = [ toString(b) for b in self.render_multiple(tokens)]
        strs = "".join([s for s in rendered if isinstance(s, str)])
        blocks = [b for b in rendered if isinstance(b, dict)]
        #Return a tuple of strings and any extra blocks we couldn't convert
        return (strs, blocks)

    def render_multiple_to_string_and_combine(self, tokens, toBlockFunc):
        """
        renderMultipleToString but combines the string with the other blocks
        with the returned block from toBlockFunc
        @param {objects} tokens
        @param {function} toBlockFunc Takes a str and returns a dict for the created
        @returns {dict[]}
        """
        strs, blocks = self.render_multiple_to_string(tokens)
        ret = []
        if strs: #If a non-empty string block
            ret = ret + [toBlockFunc(strs)]
        if blocks:
            ret = ret + blocks
        return ret

    def render_document(self, token):
        return self.render_multiple(token.children)

    def render_block_code(self, token):
        #Indented code and ``` ``` code fence
        #Notion seems really picky about the language field and the case sensitivity
        #so we match the string to the specific version that Notion.so expects
        notionSoLangs = [
            "ABAP",
            "Arduino",
            "Bash",
            "BASIC",
            "C",
            "Clojure",
            "CoffeeScript",
            "C++",
            "C#",
            "CSS",
            "Dart",
            "Diff",
            "Docker",
            "Elixir",
            "Elm",
            "Erlang",
            "Flow",
            "Fortran",
            "F#",
            "Gherkin",
            "GLSL",
            "Go",
            "GraphQL",
            "Groovy",
            "Haskell",
            "HTML",
            "Java",
            "JavaScript",
            "JSON",
            "Kotlin",
            "LaTeX",
            "Less",
            "Lisp",
            "LiveScript",
            "Lua",
            "Makefile",
            "Markdown",
            "Markup",
            "MATLAB",
            "Nix",
            "Objective-C",
            "OCaml",
            "Pascal",
            "Perl",
            "PHP",
            "Plain Text",
            "PowerShell",
            "Prolog",
            "Python",
            "R",
            "Reason",
            "Ruby",
            "Rust",
            "Sass",
            "Scala",
            "Scheme",
            "Scss",
            "Shell",
            "SQL",
            "Swift",
            "TypeScript",
            "VB.Net",
            "Verilog",
            "VHDL",
            "Visual Basic",
            "WebAssembly",
            "XML",
            "YAML"
        ]
        if token.language != "":
            matchLang = next((lang for lang in notionSoLangs if re.match(re.escape(token.language), lang, re.I)), "")
            if not matchLang:
                logger.info(f"Code block language {token.language} has no corresponding syntax in Notion.so")
        else:
            matchLang = "Plain Text"

        def blockFunc(blockStr):
            return {
                'type': CodeBlock,
                'language': matchLang,
                'title_plaintext': blockStr
            }
        return self.render_multiple_to_string_and_combine(token.children, blockFunc)

    def render_thematic_break(self, token):
        return {
            'type': DividerBlock
        }

    def render_heading(self, token):
        level = token.level
        if level > 3:
            logger.info(f"h{level} not supported in Notion.so, converting to h3")
            level = 3

        def blockFunc(blockStr):
            return {
                'type': [HeaderBlock, SubheaderBlock, SubsubheaderBlock][level-1],
                'title': blockStr
            }
        return self.render_multiple_to_string_and_combine(token.children, blockFunc)

    def render_quote(self, token):
        def blockFunc(blockStr):
            return {
                'type': QuoteBlock,
                'title': blockStr
            }
        return self.render_multiple_to_string_and_combine(token.children, blockFunc)

    def render_paragraph(self, token):
        def blockFunc(blockStr):
            return {
                'type': TextBlock,
                'title': blockStr
            }
        return self.render_multiple_to_string_and_combine(token.children, blockFunc)

    def render_list(self, token):
        #List items themselves are each blocks, so skip it and directly render
        #the children
        return self.render_multiple(token.children)

    def render_list_item(self, token):
        leaderContainsNumber = re.match(r'\d', token.leader) #Contains a number

        #Lists can have "children" (nested lists, nested images...), so we need
        #to render out all the nodes and sort through them to find the string
        #for this item and any children
        rendered = self.render_multiple(token.children)
        children = [b for b in rendered if b['type'] != TextBlock]
        strings = [s['title'] for s in rendered if s['type'] == TextBlock]

        return {
            'type': NumberedListBlock if leaderContainsNumber else BulletedListBlock,
            'title': "".join(strings),
            'children': children
        }

    def render_table(self, token):
        header_row = self.render(token.header)
        rows = [self.render(r) for r in token.children]

        schema = []

        for row in header_row:
            schema.append({"name": row, "type": "text"})

        return {
            'type': CollectionViewBlock,
            'rows': rows,
            'schema': schema
        }

    def render_table_row(self, token):
        #Rows are a concept in Notion (`CollectionRowBlock`) but notion-py provides
        #another API to use it, `.add_row()` so we just render down to an array
        #and handle in the Table block.
        return self.render_multiple(token.children)

    def render_table_cell(self, token):
        # Render straight down to a string, cells aren't a concept in Notion
        strs, blocks = self.render_multiple_to_string(token.children)
        if blocks:
            logger.info("Table cell contained non-strings (maybe an image?) and could not add...")
        return strs

    def render_strong(self, token):
        return self.render_multiple_to_string_and_combine(token.children, lambda s: f"**{s}**")

    def render_emphasis(self, token):
        return self.render_multiple_to_string_and_combine(token.children, lambda s: f"*{s}*")

    def render_inline_code(self, token):
        return self.render_multiple_to_string_and_combine(token.children, lambda s: f"`{s}`")

    def render_raw_text(self, token):
        return token.content

    def render_strikethrough(self, token):
        return self.render_multiple_to_string_and_combine(token.children, lambda s: f"~{s}~")

    def render_link(self, token):
        strs, blocks = self.render_multiple_to_string(token.children)
        return [ f"[{strs}]({token.target})" ] + blocks

    def render_escape_sequence(self, token):
        #Pretty sure this is just like \xxx type escape sequences?
        return self.render_multiple_to_string_and_combine(token.children, lambda s: f"\\{s}")

    def render_line_break(self, token):
        return ' '

    def render_image(self, token):
        #Alt text
        alt = token.title or self.render_multiple_to_string(token.children)[0]
        return {
            'type': ImageBlock,
            'display_source': token.src,
            'source': token.src,
            'caption': alt
        }


def convert(markdown):
    return mistletoe.markdown(markdown, renderer=NotionRenderer)
