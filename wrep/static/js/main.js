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

$(() => {
    $('nav.main-nav a.nav-link').each(function() {
        if ($(this).attr('href') === window.location.pathname) {
            $(this).addClass('active')
            return false
        }
    })
})
