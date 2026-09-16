import '@testing-library/jest-dom'

// jsdom doesn't implement matchMedia; useTheme() reads it to detect the
// system color-scheme preference. Default to "no preference matched" (light).
if (!window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })
}
