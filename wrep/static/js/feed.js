import {getFormParams} from './main.js'

$(() => {
    $('form').on('submit', function(e) {
        e.preventDefault()
        const params = getFormParams(this)
        const search = params.size ? `?${params.toString()}` : ''
        if (search !== window.location.search) {
            const href = `${window.location.pathname}${search}`
            window.location.href = href
        }
    })
    $('.form-reset').on('click', function(e) {
        e.preventDefault()
        if (window.location.search) {
            window.location.href = window.location.pathname
        } else {
            $(this).closest('form').get(0).reset()
        }
    })
})
