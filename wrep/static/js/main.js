;(() => {

    $(() => {

        $('nav.main-nav a.nav-link').each(function() {
            if ($(this).attr('href') === window.location.pathname) {
                $(this).addClass('active')
                return false
            }
        })
    })

})();