import { css } from "lit";

/* Layout only; colors and type come from Spectrum (Express theme) tokens with neutral fallbacks. */
export const panelStyles = css`
    :host {
        display: block;
    }

    sp-theme {
        display: block;
        min-height: 100vh;
        background: var(--spectrum-background-layer-2-color, #fff);
        color: var(--spectrum-neutral-content-color-default, #292929);
        font-family: var(--spectrum-sans-font-family-stack, adobe-clean, "Source Sans Pro", system-ui, sans-serif);
    }

    .panel {
        box-sizing: border-box;
        display: flex;
        flex-direction: column;
        gap: 16px;
        padding: 16px;
        max-width: 480px;
    }

    header h1 {
        margin: 0;
        font-size: 16px;
        font-weight: 800;
        letter-spacing: 0.04em;
    }

    .title {
        display: flex;
        flex-direction: column;
        min-width: 0;
    }

    .title .hint {
        margin: 0;
    }

    h2 {
        margin: 0;
        font-size: 13px;
        font-weight: 700;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .subtitle,
    .hint {
        margin: 4px 0 0;
        font-size: 12px;
        line-height: 1.4;
        color: var(--spectrum-neutral-subdued-content-color-default, #6e6e6e);
    }

    section {
        display: flex;
        flex-direction: column;
        gap: 6px;
        min-width: 0;
    }

    sp-field-label {
        padding-top: 4px;
    }

    sp-picker,
    sp-textfield {
        width: 100%;
        min-width: 0;
    }

    .row {
        display: flex;
        align-items: center;
        gap: 8px;
        min-width: 0;
    }

    .row.tight {
        gap: 2px;
        flex-shrink: 0;
    }

    .row.between {
        justify-content: space-between;
    }

    .row.center {
        justify-content: center;
    }

    .grow {
        flex: 1 1 auto;
    }

    .row > sp-action-button {
        flex-shrink: 0;
    }

    .full {
        width: 100%;
    }

    .run {
        margin-top: 10px;
    }

    .message {
        margin: 0;
    }

    .preview {
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 8px;
        border-radius: 8px;
        border: 1px solid var(--spectrum-gray-300, #dadada);
        background-color: var(--spectrum-gray-75, #fafafa);
        background-image: linear-gradient(45deg, #eee 25%, transparent 25%), linear-gradient(-45deg, #eee 25%, transparent 25%),
            linear-gradient(45deg, transparent 75%, #eee 75%), linear-gradient(-45deg, transparent 75%, #eee 75%);
        background-size: 16px 16px;
        background-position: 0 0, 0 8px, 8px -8px, -8px 0;
    }

    .preview img {
        display: block;
        max-width: 100%;
        max-height: 360px;
        object-fit: contain;
        box-shadow: 0 1px 4px rgba(0, 0, 0, 0.15);
    }

    .issues {
        margin: 0;
        padding-left: 20px;
        font-size: 12px;
        line-height: 1.4;
        color: var(--spectrum-negative-content-color-default, #d31510);
    }

    .metrics {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 8px 12px;
        margin: 4px 0 8px;
    }

    .metrics div {
        min-width: 0;
    }

    .metrics dt {
        font-size: 11px;
        color: var(--spectrum-neutral-subdued-content-color-default, #6e6e6e);
    }

    .metrics dd {
        margin: 0;
        font-size: 14px;
        font-weight: 700;
        font-variant-numeric: tabular-nums;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
`;
