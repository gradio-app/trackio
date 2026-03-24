<div class="trackio-loading" role="status" aria-live="polite">
  <div class="logo-stack">
    <picture class="logo-base">
      <source
        media="(prefers-color-scheme: dark)"
        srcset="/static/trackio/trackio_logo_dark.png"
      />
      <img
        src="/static/trackio/trackio_logo_light.png"
        alt=""
        class="logo-img"
      />
    </picture>
    <div class="logo-overlay" aria-hidden="true">
      <picture>
        <source
          media="(prefers-color-scheme: dark)"
          srcset="/static/trackio/trackio_logo_dark.png"
        />
        <img
          src="/static/trackio/trackio_logo_light.png"
          alt=""
          class="logo-img logo-img--gray"
        />
      </picture>
    </div>
  </div>
  <span class="sr-only">Loading</span>
</div>

<style>
  .trackio-loading {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    min-height: min(70vh, 640px);
    padding: 32px 24px;
    box-sizing: border-box;
    background: transparent;
  }

  .logo-stack {
    position: relative;
    width: min(100%, 200px);
    max-width: min(92vw, 200px);
    line-height: 0;
    background: transparent;
    isolation: isolate;
  }

  .logo-base {
    display: block;
    background: transparent;
  }

  .logo-img {
    width: 100%;
    height: auto;
    display: block;
    background: transparent;
  }

  .logo-overlay {
    position: absolute;
    left: 0;
    top: 0;
    width: 100%;
    animation: trackio-logo-sweep 4s linear infinite;
    pointer-events: none;
    background: transparent;
  }

  .logo-overlay picture {
    display: block;
    width: 100%;
    background: transparent;
  }

  .logo-overlay .logo-img {
    width: 100%;
    height: auto;
    object-position: left center;
  }

  .logo-img--gray {
    filter: grayscale(1);
  }

  @keyframes trackio-logo-sweep {
    0% {
      clip-path: inset(0 0 0 0);
    }
    50% {
      clip-path: inset(0 0 0 100%);
    }
    100% {
      clip-path: inset(0 0 0 0);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .logo-overlay {
      display: none;
    }
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }
</style>
