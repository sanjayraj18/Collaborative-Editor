import { useEffect, useRef } from "react"
import type * as Y from "yjs"
import { EditorState, Compartment } from "@codemirror/state"
import { EditorView, keymap, lineNumbers, highlightActiveLine } from "@codemirror/view"
import { defaultKeymap } from "@codemirror/commands"
import { yCollab } from "y-codemirror.next"

interface CodeEditorProps {
  doc: Y.Doc | null
  editable: boolean
}

const ROOT_KEY = "content"

const theme = EditorView.theme({
  "&": { height: "500px", fontSize: "14px" },
  ".cm-scroller": { overflow: "auto" },
})

export function CodeEditor({ doc, editable }: CodeEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef<EditorView | null>(null)
  const editableCompartment = useRef(new Compartment()).current

  useEffect(() => {
    if (!doc || !containerRef.current) return

    const ytext = doc.getText(ROOT_KEY)

    const state = EditorState.create({
        doc: ytext.toString(),
        extensions: [
        lineNumbers(),
        highlightActiveLine(),
        keymap.of(defaultKeymap),
        EditorView.lineWrapping,
        theme,
        editableCompartment.of([
            EditorView.editable.of(editable),
            EditorState.readOnly.of(!editable),
        ]),
        yCollab(ytext, null),
        ],
    })
    
    const view = new EditorView({ state, parent: containerRef.current })
    viewRef.current = view

    return () => {
      view.destroy()
      viewRef.current = null
    }
  }, [doc])

  useEffect(() => {
    viewRef.current?.dispatch({
      effects: editableCompartment.reconfigure([
        EditorView.editable.of(editable),
        EditorState.readOnly.of(!editable),
      ]),
    })
  }, [editable, editableCompartment])

  return <div ref={containerRef} className="overflow-hidden rounded-md border" />
}