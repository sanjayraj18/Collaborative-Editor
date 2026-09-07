import { createBrowserRouter } from "react-router-dom";


export const router = createBrowserRouter([
    {
        path : "/",
        lazy: () => import("./pages/LoginPage"),
    },
    {
        path: "/docs",
        lazy: () => import("./pages/DocListPage"),
    },
    {
        path: "/docs/:docId",
        lazy: () => import("./pages/DocPage"),
    },
])