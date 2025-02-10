import 'https://cdnjs.cloudflare.com/ajax/libs/jquery/3.7.1/jquery.min.js'
import 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js'

export function strunc(str, len) {
    if (str.length > len) {
        str = str.substring(0, len - 4) + ' ...'
    }
    return str
}

export function aajax(opts) {
    if (typeof opts === 'string') {
        opts = {url: opts}
    }
    return new Promise((resolve, reject) => {
        $.ajax(opts)
            .done((body, textStatus, xhr) => resolve({body, textStatus, xhr}))
            .fail((xhr, textStatus, errorThrown) => reject({xhr, textStatus, errorThrown}))
    })
}

const nformatter = new Intl.NumberFormat()
export const nf = number => number == null ? '' : nformatter.format(number)

export function escapeHtml(value) {
    return $('<p/>').text(value).html()
}

export const renderDate = value => value?.replace(/[^0-9\-]/g, '').substring(0, 10) || ''

export async function renderError(err) {
    const lines = []
    if (err) {
        if (err.xhr) {
            lines.push(`Status: ${err.xhr.status}`)
        }
        if (err.errorThrown) {
            lines.push(`Error: ${err.errorThrown}`)
        }
        if (!lines.length) {
            lines.push(`Error: ${err}`)
        }
    }
    return $('<pre/>').text(lines.join('\n'))
}


export class StaticComponent {
    constructor(content) {
        this.content = content
    }
    async build() {
        return this.content
    }
}



class Cache {
    constructor(prefix, config) {
        this.prefix = prefix || ''
        this.config = config
    }

    async fetch(key) {
        let item = this.getItem(key)
        if (item?.expiry > +new Date) {
            return item.value
        }
        return await this.load(key)
    }

    async load(key) {
        const {duration, source} = this.config[key]
        const value = typeof source === 'function'
            ? await source()
            : (await aajax(source)).body
        const item = {value, expiry: +new Date + duration}
        this.setItem(key, item)
        return value
    }

    getItem(key) {
        return JSON.parse(localStorage.getItem(this.prefix+key) || 'null')
    }

    setItem(key, item) {
        localStorage.setItem(this.prefix+key, JSON.stringify(item))
    }
}

export const cache = new Cache('wrdata_', {
    states: {
        duration: 5 * 60 * 1000,
        source: '/api/v0/states',
    },
    stats: {
        duration: 5 * 60 * 1000,
        source: '/api/v0/_db',
    },
    naicsRoots: {
        duration: 30 * 60 * 1000,
        source: '/api/v0/naics?depth_max=0',
    },
})
