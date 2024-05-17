;(() => {

    $(() => {
        $('form').on('submit', function(e) {
            e.preventDefault()
            const data = new FormData(this)
            const params = new URLSearchParams()
            for (const [field, value] of data.entries()) {
                if (value) {
                    params.set(field, value)
                }
            }
            const search = params.size ? `?${params.toString()}` : ''
            if (search !== window.location.search) {
                const href = `${window.location.pathname}${search}`
                window.location.href = href
            }
        })
        $('.form-reset').on('click', function() {
            if (window.location.search) {
                window.location.href = window.location.pathname
            } else {
                $(this).closest('form').get(0).reset()
            }
        })
    })

})();