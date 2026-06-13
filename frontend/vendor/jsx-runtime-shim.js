// Shim minimal de react/jsx-runtime pour les bundles UMD (ex. xyflow-react.umd.js)
// qui s'attendent à trouver window.jsxRuntime.{jsx,jsxs,Fragment} en environnement
// sans require/AMD. Doit être chargé après react.production.min.js.
(function () {
  function jsx(type, props, key) {
    var config = props ? Object.assign({}, props) : {};
    if (key !== undefined) config.key = '' + key;
    return window.React.createElement(type, config);
  }
  window.jsxRuntime = {
    jsx: jsx,
    jsxs: jsx,
    Fragment: window.React.Fragment,
  };
})();
