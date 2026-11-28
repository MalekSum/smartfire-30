// model_stub.h : modèle provisoire à règles, à remplacer par model.h généré par micromlgen
namespace Eloquent { namespace ML { namespace Port {
class RandomForest {
public:
int predict(float *x) {
float h = x[1], gaz = x[2], flame = x[3], dt = x[4];
if ((flame > 0.5f && gaz > 1500) || (dt > 0.5f && gaz > 2000)) return 2;
if (gaz > 1500 || h > 75) return 1;
return 0;
}
};
}}}