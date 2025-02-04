export function getFormParams(form) {
    const params = new URLSearchParams
    const formData = new FormData($(form).get(0))
    for (const [field, value] of formData.entries()) {
        if (value.length) {
            params.append(field, value)
        }
    }
    return params
}

export function aajax(opts) {
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

export async function renderError(err) {
    const lines = []
    if (err) {
        if (err.xhr) {
            lines.push(`Status: ${err.xhr.status}`)
        }
        if (err.errorThrown) {
            lines.push(`Error: ${err.errorThrown}`)
        }
    }
    return $('<pre/>').text(lines.join('\n'))
}
