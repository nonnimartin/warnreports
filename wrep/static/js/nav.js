const staticHtml =
`
<nav class="nav main-nav nav-pills">
  <a class="nav-link" href="/">Home</a>
  <a class="nav-link" href="/search">Search</a>
  <a class="nav-link" href="/feed">Feed</a>
  <a class="nav-link" href="/api/docs">API</a>
  <a class="nav-link" href="/about">About</a>
</nav>`

export async function renderNav(target) {
    const nav = $(staticHtml)
    $('a.nav-link', nav).each(function() {
        if ($(this).attr('href') === window.location.pathname) {
            $(this).addClass('active')
            return false
        }
    })
    $(target).html(nav)
}
