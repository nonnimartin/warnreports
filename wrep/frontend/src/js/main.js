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
export const nf = number => nformatter.format(number)

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

const CollectionStats = new Map
CollectionStats.expiry = 1 * 60 * 1000
CollectionStats.at = null

export async function getCollectionStats() {
    const cache = CollectionStats
    if (cache.size === 0 || cache.at < +new Date - cache.expiry) {
        const {body} = await aajax('/api/v0/_db')
        cache.clear()
        for (const entry of Object.entries(body.collections)) {
            cache.set(...entry)
        }
        cache.at = +new Date
    }
    return cache
}