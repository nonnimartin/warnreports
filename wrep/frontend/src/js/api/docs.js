import 'https://unpkg.com/rapidoc/dist/rapidoc-min.js'

function initRapi() {
    const rapi = $('rapi-doc')
    const checkStart = +new Date
    const iflag = setInterval(
        () => {
            const ctx = rapi.get(0).shadowRoot
            if (!ctx || !$('#auth', ctx).length) {
                console.log('nope')
                if (+new Date - checkStart < 10 * 1000) {
                    return
                }
                console.error('giving up')
            }
            clearInterval(iflag)
            setTimeout(() => init(ctx))
        },
        50)
    setTimeout(() => clearInterval(iflag), 10 * 1000)
    const hides = [
        'header',
        '#auth',
        'div.table-title[part="label-selected-server"]',
    ]
    function init(ctx) {
        $(hides.join(','), ctx).hide()
        $('#operations-top', ctx).next('div').hide()
        const generalHeader = $('.section-gap.section-tag > .section-tag-header', ctx)
        if (generalHeader.length === 1) {
            generalHeader.hide()
        }
        $('section, .section-gap', ctx).css({paddingLeft: '4px'})
        $('summary.endpoint-head', ctx).css({padding: '6px 0'})
        rapi.show()
    }
}

const rapiHtml =
`<rapi-doc spec-url="/openapi.json" theme="dark" render-style="view" class="hidden"></rapi-doc>`

export async function renderPage(target) {
    $(target).html(rapiHtml)
    initRapi()
}
