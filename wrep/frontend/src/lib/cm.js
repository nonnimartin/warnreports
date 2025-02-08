
import 'https://cdnjs.cloudflare.com/ajax/libs/codemirror/6.65.7/codemirror.min.js'
import 'https://cdnjs.cloudflare.com/ajax/libs/codemirror/6.65.7/mode/xml/xml.min.js'

const defaults = {
    theme: 'seti',
    readonly: true,
}

export default async function cm(target, opts) {
    opts = {...defaults, ...(opts || {})}
    target = $(target || '<div/>')
    return new CodeMirror(target.get(0), opts)
}