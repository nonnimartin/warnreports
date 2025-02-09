
import 'https://cdnjs.cloudflare.com/ajax/libs/codemirror/6.65.7/codemirror.min.js'
import 'https://cdnjs.cloudflare.com/ajax/libs/codemirror/6.65.7/mode/xml/xml.min.js'

const defaults = {
    // theme: 'rubyblue',
    theme: 'seti',
    readonly: true,
}

export default function cm(opts) {
    opts = {...defaults, ...(opts || {})}
    const target = $(opts.target || '<div/>').addClass('cm-target')
    const api = new CodeMirror(target.get(0), opts)
    api.target = target
    return api
}
