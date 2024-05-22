import {getFormParams} from './main.js'

$(() => {
    const form = $('form')
    form.on('submit', function(e) {
        e.preventDefault()
        const params = getFormParams(form)
        for (const key of params.keys()) {
            params.set(key, params.getAll(key).join(','))
        }
        const search = params.size ? `?${params.toString()}` : ''
        if (search !== window.location.search) {
            const href = `${window.location.pathname}${search}`
            window.location.href = href
        }
    })
    $('.form-reset', form).on('click', function(e) {
        e.preventDefault()
        if (window.location.search) {
            window.location.href = window.location.pathname
        } else {
            form.get(0).reset()
        }
    })
})
