import 'prelude.just'

# Prepare the working parser and WASM as a local Zed dev extension under .tmp.
prepare:
    @renode-zed-prepare

# Prepare the extension and open a separate Zed instance for the editor review.
review:
    @renode-zed-review
