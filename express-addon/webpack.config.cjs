const fs = require("fs");
const path = require("path");
const HtmlWebpackPlugin = require("html-webpack-plugin");
const CopyWebpackPlugin = require("copy-webpack-plugin");

const isEnvProduction = process.env.NODE_ENV === "production";

module.exports = {
    mode: isEnvProduction ? "production" : "development",
    devtool: isEnvProduction ? "source-map" : "eval-source-map",
    entry: "./src/index.js",
    experiments: {
        outputModule: true
    },
    output: {
        pathinfo: !isEnvProduction,
        path: path.resolve(__dirname, "dist"),
        module: true,
        filename: "index.js"
    },
    externalsType: "module",
    externalsPresets: { web: true },
    plugins: [
        new HtmlWebpackPlugin({
            // Static HTML, read on every compilation. Passing it as `template` would run it through
            // the plugin's lodash loader, whose `with` statement webpack rejects in ESM output.
            templateContent: () => fs.readFileSync(path.resolve(__dirname, "src/index.html"), "utf8"),
            scriptLoading: "module"
        }),
        new CopyWebpackPlugin({
            patterns: [{ from: "src/*.json", to: "[name][ext]" }]
        })
    ],
    module: {
        rules: [
            {
                test: /\.(js)$/,
                exclude: /node_modules/,
                use: ["babel-loader"]
            },
            {
                test: /(\.css)$/,
                use: ["style-loader", "css-loader"]
            }
        ]
    },
    performance: {
        // Spectrum Web Components' Express theme alone is about 330 KiB of CSS-in-JS, so webpack's
        // generic 244 KiB web budget cannot be met. Budget the real panel size instead, so that an
        // accidental extra theme or library still fails loudly.
        hints: isEnvProduction ? "error" : false,
        maxAssetSize: 768 * 1024,
        maxEntrypointSize: 768 * 1024
    },
    resolve: {
        extensions: [".js", ".css"]
    }
};
