import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://127.0.0.1:8321' },
  },
  build: {
    // Mermaid's lazy layout engines (elk, cytoscape) are larger than the default limit and load only when a diagram needs them
    chunkSizeWarningLimit: 1500,
    rolldownOptions: {
      output: {
        // libraries loaded up front get chunks of their own, so an update re-downloads only the app's code;
        // each group takes its dependencies along
        codeSplitting: {
          groups: [
            { name: 'react', test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/ },
            {
              name: 'syntax',
              // mermaid carries its own katex, loaded with mermaid
              test: (id) => /node_modules[\\/](katex|rehype-katex|highlight\.js|lowlight|rehype-highlight)[\\/]/.test(id) && !/[\\/]mermaid[\\/]/.test(id),
            },
            { name: 'markdown', test: /node_modules[\\/](react-markdown|remark-gfm|remark-math|unified|unist-util-visit)[\\/]/ },
          ],
        },
      },
    },
  },
})
