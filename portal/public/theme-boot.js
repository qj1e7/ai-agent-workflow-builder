(function () {
  var theme = null
  try {
    var stored = window.localStorage.getItem('portal.theme')
    if (stored === 'light' || stored === 'dark') theme = stored
  } catch {
    // Storage is blocked, so the system preference decides.
  }
  if (theme === null) {
    try {
      theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    } catch {
      theme = 'light'
    }
  }
  document.documentElement.dataset.theme = theme
})()
